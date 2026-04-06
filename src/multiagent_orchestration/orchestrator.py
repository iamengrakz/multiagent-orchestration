"""
orchestrator.py — DAGOrchestrator
===================================
Book reference: Chapters 4 and 5

The main execution engine.  Given a :class:`~multiagent_orchestration.dag.DirectedAcyclicGraph`
of :class:`~multiagent_orchestration.contracts.MCPToolContract` nodes, it:

1. Runs a topological sort to establish execution order.
2. For each tool, checks the :class:`~multiagent_orchestration.loop_detector.InvocationFingerprinter`.
3. If the tool is ``side_effecting``, routes through :class:`~multiagent_orchestration.idempotency.IdempotencyMiddleware`.
4. Emits structured log events before and after each invocation.
5. Collects results in an :class:`OrchestrationResult` and halts on first
   ``Err`` unless ``config.continue_on_error`` is ``True``.

Usage (Chapter 5, Listing 5.1)::

    dag = DirectedAcyclicGraph()
    dag.add_edge(planner, searcher)
    dag.add_edge(searcher, summariser)

    config = OrchestrationConfig(max_loop_repeats=1)
    orchestrator = DAGOrchestrator(config=config)
    outcome = orchestrator.run(dag, initial_inputs={"planner": {"query": "..."}})
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from multiagent_orchestration.dag import DirectedAcyclicGraph
from multiagent_orchestration.idempotency import IdempotencyMiddleware, InMemoryStore
from multiagent_orchestration.loop_detector import InvocationFingerprinter, LoopError
from multiagent_orchestration.observability import StructuredLogger
from multiagent_orchestration.result import Ok, Err, Result


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class OrchestrationConfig:
    """Tuning knobs for the orchestrator.

    Book reference: Chapter 5, §5.2 — "Configuring the Orchestrator"

    Attributes:
        max_loop_repeats: Passed to :class:`InvocationFingerprinter`.
            Default ``1`` means any repeated tool+args combo is an error.
        continue_on_error: When ``True``, tool failures are recorded but
            execution continues to the next node.  Default ``False``.
        verbose: Enables verbose structured logging.
        idempotency_store: Optional custom store; defaults to
            :class:`~multiagent_orchestration.idempotency.InMemoryStore`.
    """

    max_loop_repeats: int = 1
    continue_on_error: bool = False
    verbose: bool = False
    idempotency_store: Any = None  # IdempotencyStore; default constructed below


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class OrchestrationResult:
    """Outcome of a complete pipeline run.

    Book reference: Chapter 5, §5.4 — "Collecting Results"

    Attributes:
        trace_id: UUID4 for the run; appears in all log events.
        outputs: Mapping of tool name → ``Ok``/``Err`` result.
        halted_at: Tool name where execution stopped, or ``None`` if complete.
        loop_errors: Fingerprints of detected loops.
    """

    trace_id: str
    outputs: dict[str, Result] = field(default_factory=dict)
    halted_at: str | None = None
    loop_errors: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.halted_at is None and all(
            r.is_ok() for r in self.outputs.values()
        )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class DAGOrchestrator:
    """Executes a :class:`DirectedAcyclicGraph` of tool contracts.

    Book reference: Chapter 4, §4.4 — "The DAGOrchestrator Class"

    Args:
        config: :class:`OrchestrationConfig` instance.
        logger: Optional :class:`StructuredLogger`; one is created if absent.
    """

    def __init__(
        self,
        config: OrchestrationConfig | None = None,
        logger: StructuredLogger | None = None,
    ) -> None:
        self._config = config or OrchestrationConfig()
        self._logger = logger or StructuredLogger(verbose=self._config.verbose)
        store = self._config.idempotency_store or InMemoryStore()
        self._idempotency = IdempotencyMiddleware(store)

    def run(
        self,
        dag: DirectedAcyclicGraph,
        initial_inputs: dict[str, dict[str, Any]],
    ) -> OrchestrationResult:
        """Execute all tools in topological order.

        Args:
            dag: The pipeline graph.
            initial_inputs: Mapping of tool name → input dict.  Tools that
                produce outputs automatically feed downstream tools if those
                tools have no entry in ``initial_inputs``.

        Returns:
            An :class:`OrchestrationResult` describing the full run.
        """
        trace_id = str(uuid.uuid4())
        detector = InvocationFingerprinter(max_repeats=self._config.max_loop_repeats)
        result = OrchestrationResult(trace_id=trace_id)
        accumulated_outputs: dict[str, Any] = {}

        self._logger.info(
            "pipeline_start",
            trace_id=trace_id,
            tool_count=len(dag),
        )

        for tool in dag:
            inputs = initial_inputs.get(tool.name, {})
            # Merge accumulated upstream outputs into inputs when no explicit
            # input was provided.  Filter to the tool's declared properties so
            # that additionalProperties validation does not reject extra keys
            # produced by sibling or ancestor tools (Chapter 5, §5.3).
            if not inputs and accumulated_outputs:
                declared = set(tool.input_schema.properties.keys())
                if declared:
                    inputs = {k: v for k, v in accumulated_outputs.items()
                              if k in declared}
                else:
                    inputs = dict(accumulated_outputs)

            # --- Loop detection (Chapter 6) ---
            try:
                fp = detector.record(tool, inputs)
            except LoopError as exc:
                self._logger.book_pattern(
                    "🔁  LOOP PREVENTED — orchestrator terminated before infinite tool call ✓",
                    trace_id=trace_id,
                    tool=tool.name,
                    fingerprint=exc.fingerprint,
                )
                result.loop_errors.append(exc.fingerprint)
                result.halted_at = tool.name
                break

            self._logger.info(
                "tool_call_start",
                trace_id=trace_id,
                tool=tool.name,
                version=tool.version,
                fingerprint=fp,
            )

            # --- Idempotency middleware (Chapter 8) ---
            if tool.side_effecting or tool.idempotent:
                call_result = self._idempotency.call(tool, inputs)
            else:
                call_result = tool.call(inputs)

            result.outputs[tool.name] = call_result

            if isinstance(call_result, Ok):
                self._logger.info(
                    "tool_call_success",
                    trace_id=trace_id,
                    tool=tool.name,
                )
                accumulated_outputs.update(call_result.value)
            else:
                self._logger.error(
                    "tool_call_error",
                    trace_id=trace_id,
                    tool=tool.name,
                    error=str(call_result.error),
                )
                if not self._config.continue_on_error:
                    result.halted_at = tool.name
                    break

        self._logger.info(
            "pipeline_end",
            trace_id=trace_id,
            succeeded=result.succeeded,
            halted_at=result.halted_at,
        )
        return result
