"""
saga.py — SagaOrchestrator: Compensating Transactions and Automatic Rollback
=============================================================================
Book reference: Chapter 13 — "Saga Pattern: Rollback When Downstream Tools Fail"

The standard :class:`~multiagent_orchestration.orchestrator.DAGOrchestrator`
records failures and can ``continue_on_error``, but the caller is responsible
for any business-level undo logic.  This module adds first-class support for
**compensating transactions** — the Saga pattern from distributed systems.

The Problem (Chapter 13, §13.1)
--------------------------------
Consider a three-tool pipeline:

    ReserveInventory → ChargeCreditCard → SendConfirmationEmail

If ``ChargeCreditCard`` fails:
- ``ReserveInventory`` has already run and locked stock.
- Without compensation, inventory stays locked forever.
- The customer never receives a charge, but stock is unavailable.

The Saga pattern fixes this by pairing each forward action with a
**compensating action** that undoes it.  If any step fails, the orchestrator
walks backwards through the already-completed steps and runs their compensators.

Design (Chapter 13, §13.2)
---------------------------
- :class:`SagaStep` pairs a :class:`~multiagent_orchestration.contracts.MCPToolContract`
  with an optional ``compensator`` (also an ``MCPToolContract``).
- :class:`SagaOrchestrator` executes steps in order.  On failure, it calls
  each completed step's compensator in **reverse order** (LIFO).
- Compensation failures are recorded but do not halt the compensation chain —
  you still want to try to undo as much as possible.
- Results are collected in a :class:`SagaResult` that separates forward
  outcomes from compensation outcomes.

Usage (Chapter 13, Listing 13.3)::

    saga = SagaOrchestrator()

    saga.add_step(SagaStep(
        tool=ReserveInventoryTool(),
        compensator=ReleaseInventoryTool(),   # undo if downstream fails
    ))
    saga.add_step(SagaStep(
        tool=ChargeCreditCardTool(),
        compensator=RefundCreditCardTool(),
    ))
    saga.add_step(SagaStep(
        tool=SendConfirmationEmailTool(),
        # no compensator — email already sent, can't unsend
    ))

    result = saga.run(initial_inputs={"order_id": "ORD-001", ...})

    if result.failed:
        print("Saga failed at:", result.failed_at_step)
        print("Compensations run:", result.compensation_outcomes)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from multiagent_orchestration.contracts import MCPToolContract
from multiagent_orchestration.idempotency import IdempotencyMiddleware, InMemoryStore
from multiagent_orchestration.loop_detector import InvocationFingerprinter, LoopError
from multiagent_orchestration.observability import StructuredLogger
from multiagent_orchestration.result import Ok, Err, Result


# ---------------------------------------------------------------------------
# SagaStep
# ---------------------------------------------------------------------------

@dataclass
class SagaStep:
    """A forward action paired with its optional compensating action.

    Book reference: Chapter 13, §13.3 — "The SagaStep Dataclass"

    Attributes:
        tool: The forward :class:`~multiagent_orchestration.contracts.MCPToolContract`.
        compensator: Optional tool to call if a later step fails.
            When ``None``, this step is treated as non-compensatable (e.g.
            sending an email — you can't unsend it, so document that fact).
        name: Human-readable step name for logs.  Defaults to ``tool.name``.
        compensator_inputs: Optional static inputs for the compensator.
            When ``None``, the compensator receives the forward step's *output*
            merged with any saga-level context (same propagation as the
            main orchestrator).
    """

    tool: MCPToolContract
    compensator: MCPToolContract | None = None
    name: str = ""
    compensator_inputs: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.name:
            self.name = self.tool.name


# ---------------------------------------------------------------------------
# SagaResult
# ---------------------------------------------------------------------------

@dataclass
class SagaResult:
    """Outcome of a full saga run.

    Book reference: Chapter 13, §13.5 — "Interpreting SagaResult"

    Attributes:
        succeeded: ``True`` if all forward steps completed without error.
        failed_at_step: Name of the step that triggered rollback, or ``None``.
        forward_outputs: Mapping of step name → forward ``Ok``/``Err`` result.
        compensation_outcomes: Mapping of step name → compensation ``Ok``/``Err``,
            populated only for steps that were compensated.
        uncompensated_steps: Names of completed steps that had no compensator.
    """

    succeeded: bool
    failed_at_step: str | None = None
    forward_outputs: dict[str, Result] = field(default_factory=dict)
    compensation_outcomes: dict[str, Result] = field(default_factory=dict)
    uncompensated_steps: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return not self.succeeded

    @property
    def fully_compensated(self) -> bool:
        """True if every completed step with a compensator was successfully compensated."""
        return all(
            isinstance(r, Ok)
            for r in self.compensation_outcomes.values()
        )


# ---------------------------------------------------------------------------
# SagaOrchestrator
# ---------------------------------------------------------------------------

class SagaOrchestrator:
    """Executes a sequence of :class:`SagaStep` with automatic rollback on failure.

    Book reference: Chapter 13, §13.4 — "The SagaOrchestrator"

    Args:
        logger: Optional :class:`StructuredLogger`.
        idempotency_store: Optional idempotency store; defaults to
            :class:`~multiagent_orchestration.idempotency.InMemoryStore`.
        loop_detector: Optional :class:`InvocationFingerprinter`.
    """

    def __init__(
        self,
        logger: StructuredLogger | None = None,
        idempotency_store: Any = None,
        loop_detector: InvocationFingerprinter | None = None,
    ) -> None:
        self._logger = logger or StructuredLogger(verbose=False)
        store = idempotency_store or InMemoryStore()
        self._idempotency = IdempotencyMiddleware(store)
        self._loop_detector = loop_detector or InvocationFingerprinter()
        self._steps: list[SagaStep] = []

    def add_step(self, step: SagaStep) -> "SagaOrchestrator":
        """Append *step* to the saga.  Returns ``self`` for chaining."""
        self._steps.append(step)
        return self

    def run(self, initial_inputs: dict[str, Any]) -> SagaResult:
        """Execute all steps forward; rollback completed steps on failure.

        Args:
            initial_inputs: Starting inputs for the first step.  Subsequent
                steps receive the accumulated outputs from all prior steps,
                filtered to their declared input schema (same as
                ``DAGOrchestrator``).

        Returns:
            A :class:`SagaResult` describing the full forward + compensation run.
        """
        import uuid
        trace_id = str(uuid.uuid4())
        result = SagaResult(succeeded=False)
        accumulated: dict[str, Any] = dict(initial_inputs)
        completed_steps: list[tuple[SagaStep, dict[str, Any]]] = []  # (step, inputs_used)

        self._logger.info("saga_start", trace_id=trace_id, step_count=len(self._steps))

        # ── Forward pass ────────────────────────────────────────────────────
        for step in self._steps:
            # Filter accumulated outputs to this tool's declared schema.
            # If the tool has no declared properties (empty schema), pass nothing
            # from accumulated — it expects only explicit initial_inputs.
            # This prevents 'additionalProperties' validation errors.
            declared = set(step.tool.input_schema.properties.keys())
            if declared:
                inputs = {k: v for k, v in accumulated.items() if k in declared}
            else:
                inputs = {}  # tool expects no inputs from prior steps

            # Loop detection
            try:
                self._loop_detector.record(step.tool, inputs)
            except LoopError as exc:
                self._logger.book_pattern(
                    "🔁  LOOP PREVENTED in Saga — rolling back completed steps",
                    trace_id=trace_id,
                    step=step.name,
                    fingerprint=exc.fingerprint,
                )
                result.failed_at_step = step.name
                self._compensate(completed_steps, result, trace_id)
                return result

            self._logger.info("saga_step_start", trace_id=trace_id, step=step.name)

            # Execute (use idempotency middleware for side-effecting tools)
            if step.tool.side_effecting or step.tool.idempotent:
                step_result = self._idempotency.call(step.tool, inputs)
            else:
                step_result = step.tool.call(inputs)

            result.forward_outputs[step.name] = step_result

            if isinstance(step_result, Ok):
                self._logger.info("saga_step_success", trace_id=trace_id, step=step.name)
                accumulated.update(step_result.value)
                completed_steps.append((step, inputs))
            else:
                self._logger.error(
                    "saga_step_failed",
                    trace_id=trace_id,
                    step=step.name,
                    error=str(step_result.error),
                )
                result.failed_at_step = step.name
                # ── Trigger rollback ────────────────────────────────────────
                self._compensate(completed_steps, result, trace_id)
                return result

        result.succeeded = True
        self._logger.info("saga_complete", trace_id=trace_id, succeeded=True)
        return result

    # ------------------------------------------------------------------
    # Compensation (rollback)
    # ------------------------------------------------------------------

    def _compensate(
        self,
        completed_steps: list[tuple[SagaStep, dict[str, Any]]],
        result: SagaResult,
        trace_id: str,
    ) -> None:
        """Run compensators in LIFO order for all completed steps.

        Book reference: Chapter 13, §13.6 — "The Compensation Walk"

        Compensation failures are recorded but do not halt the chain —
        we try to compensate every step regardless.
        """
        self._logger.info(
            "saga_rollback_start",
            trace_id=trace_id,
            steps_to_compensate=len(completed_steps),
        )

        for step, forward_inputs in reversed(completed_steps):
            if step.compensator is None:
                self._logger.warn(
                    "saga_step_no_compensator",
                    trace_id=trace_id,
                    step=step.name,
                    note="Step completed but has no compensator — manual review required.",
                )
                result.uncompensated_steps.append(step.name)
                continue

            # Determine compensator inputs
            comp_inputs = step.compensator_inputs if step.compensator_inputs is not None else forward_inputs

            # Filter to compensator's declared schema
            comp_declared = set(step.compensator.input_schema.properties.keys())
            if comp_declared:
                comp_inputs = {k: v for k, v in comp_inputs.items() if k in comp_declared}

            self._logger.info(
                "saga_compensating",
                trace_id=trace_id,
                step=step.name,
                compensator=step.compensator.name,
            )

            comp_result = step.compensator.call(comp_inputs)
            result.compensation_outcomes[step.name] = comp_result

            if isinstance(comp_result, Ok):
                self._logger.info(
                    "saga_compensation_success",
                    trace_id=trace_id,
                    step=step.name,
                )
            else:
                self._logger.error(
                    "saga_compensation_failed",
                    trace_id=trace_id,
                    step=step.name,
                    error=str(comp_result.error),
                    note="Manual intervention may be required for this step.",
                )

        self._logger.info("saga_rollback_complete", trace_id=trace_id)
