"""
examples/hero_demo/run.py
==========================
Book reference: Chapters 6, 13, 15

The editor's "hero demo" — a single, self-contained script that walks through
a complete failure scenario using three production patterns in sequence:

    ACT 1 — Semantic Loop Detection (Chapter 15)
             A misbehaving planner issues paraphrased queries.
             The CompositeLoopDetector catches it before it spins forever.

    ACT 2 — Saga Compensation (Chapter 13)
             A three-step order pipeline: Reserve → Charge → Notify.
             The Charge step fails. The Saga walks back in LIFO order,
             releasing the inventory reservation automatically.

    ACT 3 — Full Composition (Chapters 6, 13, 15 combined)
             A pipeline that uses CompositeLoopDetector AND SagaOrchestrator
             together, showing how the patterns compose cleanly.

Run with zero external dependencies:

    python examples/hero_demo/run.py

Expected console output landmarks:

    🔍  SEMANTIC LOOP DETECTED — paraphrased query caught before re-execution ✓
    💸  SAGA STEP FAILED: charge_card — rolling back in LIFO order
    ↩️   COMPENSATED: reserve_inventory → release_inventory ✓
    ✅  SAGA FULLY COMPENSATED — no leaked resources ✓
"""

from __future__ import annotations

import pathlib
import sys
import time

# Make the library importable when running from repo root
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

from multiagent_orchestration.contracts import MCPToolContract, ToolSchema
from multiagent_orchestration.loop_detector import LoopError
from multiagent_orchestration.observability import StructuredLogger
from multiagent_orchestration.result import Ok, Err
from multiagent_orchestration.saga import SagaOrchestrator, SagaResult, SagaStep
from multiagent_orchestration.semantic_loop_detector import (
    CompositeLoopDetector,
    SemanticLoopError,
    TFIDFEmbedder,
)
from multiagent_orchestration.state_sync import (
    AgentEvent,
    InMemoryEventStore,
)

# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

LOGGER = StructuredLogger(verbose=False)

def _banner(title: str) -> None:
    width = 62
    print(f"\n{'─' * width}")
    print(f"  {title}")
    print(f"{'─' * width}")

def _pause(ms: int = 80) -> None:
    time.sleep(ms / 1000)


# ─────────────────────────────────────────────────────────────────────────────
# ACT 1 — Semantic Loop Detection
# ─────────────────────────────────────────────────────────────────────────────

class WebSearchTool(MCPToolContract):
    name = "web_search"
    version = "1.0.0"
    description = "Search the web for a query."
    input_schema = ToolSchema(
        required=["query"],
        properties={"query": {"type": "string"}},
    )
    output_schema = ToolSchema(
        required=["results"],
        properties={"results": {"type": "array", "items": {"type": "string"}}},
    )
    def execute(self, inputs):
        return {"results": [f"[stub] result for: {inputs['query']}"]}


def act1_semantic_loop_detection() -> None:
    _banner("ACT 1 — Semantic Loop Detection  (Chapter 15)")

    print("""
  Scenario:
    A misbehaving planner calls web_search three times with
    increasing paraphrase — different words, same intent.

    Layer 1 (SHA-256):   misses paraphrases — they look different
    Layer 2 (TF-IDF):    catches them — cosine similarity ≥ threshold
""")

    tool = WebSearchTool()
    embedder = TFIDFEmbedder()
    detector = CompositeLoopDetector(
        max_repeats=1,
        semantic_threshold=0.82,
        embedder=embedder,
    )

    queries = [
        "multi-agent orchestration production patterns",   # original
        "production patterns multi agent orchestration",   # paraphrase #1
        "orchestration patterns for production multi-agent systems",  # paraphrase #2
    ]

    for i, query in enumerate(queries, start=1):
        inputs = {"query": query}
        print(f"  Call {i}: web_search(query={query!r})")
        _pause()
        try:
            fp = detector.record(tool, inputs)
            result = tool.call(inputs)
            print(f"    ✓ executed  (fingerprint: {fp[:10]}…)")
        except LoopError as exc:
            print(f"    [exact match] LoopError — fingerprint: {exc.fingerprint[:10]}…")
            LOGGER.book_pattern(
                "🔍  SEMANTIC LOOP DETECTED — exact duplicate caught ✓",
                query=query,
            )
            break
        except SemanticLoopError as exc:
            print(f"    [semantic match] similarity={exc.similarity:.3f} ≥ {exc.threshold}")
            LOGGER.book_pattern(
                "🔍  SEMANTIC LOOP DETECTED — paraphrased query caught before re-execution ✓",
                query=query,
                similarity=f"{exc.similarity:.3f}",
                threshold=str(exc.threshold),
            )
            print(f"\n  🔍  SEMANTIC LOOP DETECTED — paraphrased query caught before re-execution ✓")
            break

    print(f"\n  Window contents after detection: {detector._semantic.current_window_length} entries")
    print("  ACT 1 COMPLETE.\n")


# ─────────────────────────────────────────────────────────────────────────────
# ACT 2 — Saga Compensation
# ─────────────────────────────────────────────────────────────────────────────

class ReserveInventoryTool(MCPToolContract):
    name = "reserve_inventory"
    version = "1.0.0"
    description = "Lock stock for an order."
    input_schema = ToolSchema(
        required=["order_id"],
        properties={"order_id": {"type": "string"}},
    )
    output_schema = ToolSchema(
        required=["reserved"],
        properties={"reserved": {"type": "boolean"}, "sku": {"type": "string"}},
    )
    def execute(self, inputs):
        print(f"    → ReserveInventory: locking stock for {inputs['order_id']}")
        _pause()
        return {"reserved": True, "sku": "SKU-9001"}


class ReleaseInventoryTool(MCPToolContract):
    """Compensator for ReserveInventoryTool."""
    name = "release_inventory"
    version = "1.0.0"
    description = "Release locked stock — compensates ReserveInventory."
    input_schema = ToolSchema(
        required=["order_id"],
        properties={"order_id": {"type": "string"}},
    )
    output_schema = ToolSchema(
        required=["released"],
        properties={"released": {"type": "boolean"}},
    )
    def execute(self, inputs):
        print(f"    ← ReleaseInventory: stock unlocked for {inputs['order_id']}")
        _pause()
        return {"released": True}


class ChargeCardTool(MCPToolContract):
    name = "charge_card"
    version = "1.0.0"
    description = "Charge the customer's credit card."
    input_schema = ToolSchema(
        required=["order_id"],
        properties={"order_id": {"type": "string"}},
    )
    output_schema = ToolSchema(required=[], properties={})

    def execute(self, inputs):
        print(f"    → ChargeCard: attempting charge for {inputs['order_id']}…")
        _pause(200)
        raise RuntimeError("Payment gateway timeout — card not charged")


class SendNotificationTool(MCPToolContract):
    name = "send_notification"
    version = "1.0.0"
    description = "Send order confirmation email."
    input_schema = ToolSchema(
        required=["order_id"],
        properties={"order_id": {"type": "string"}},
    )
    output_schema = ToolSchema(
        required=["sent"],
        properties={"sent": {"type": "boolean"}},
    )
    def execute(self, inputs):
        print(f"    → SendNotification: email sent for {inputs['order_id']}")
        _pause()
        return {"sent": True}


def act2_saga_compensation() -> None:
    _banner("ACT 2 — Saga Compensation  (Chapter 13)")

    print("""
  Scenario:
    Three-step order pipeline:
      1. ReserveInventory  (compensator: ReleaseInventory)
      2. ChargeCard        (fails — payment gateway timeout)
      3. SendNotification  (never reached)

    Without saga: inventory stays locked forever.
    With saga:    ReleaseInventory runs automatically in LIFO order.
""")

    saga = SagaOrchestrator()
    saga.add_step(SagaStep(
        tool=ReserveInventoryTool(),
        compensator=ReleaseInventoryTool(),
    ))
    saga.add_step(SagaStep(
        tool=ChargeCardTool(),
        compensator=None,        # no compensator — card was never charged
    ))
    saga.add_step(SagaStep(
        tool=SendNotificationTool(),
        compensator=None,        # never reached
    ))

    print("  Running forward pass…\n")
    result: SagaResult = saga.run(initial_inputs={"order_id": "ORD-2026-001"})

    print(f"\n  💸  SAGA STEP FAILED: {result.failed_at_step} — rolling back in LIFO order\n")
    _pause(100)

    # Show compensation outcome
    for step_name, comp_result in result.compensation_outcomes.items():
        if isinstance(comp_result, Ok):
            print(f"  ↩️   COMPENSATED: {step_name} → {_comp_name(step_name)} ✓")
        else:
            print(f"  ✗   COMPENSATION FAILED: {step_name} — {comp_result.error}")

    for step_name in result.uncompensated_steps:
        print(f"  ⚠️   NO COMPENSATOR: {step_name} (step was not reached or has no undo)")

    print()
    if result.fully_compensated:
        print("  ✅  SAGA FULLY COMPENSATED — no leaked resources ✓")
    else:
        print("  ⚠️   SAGA PARTIALLY COMPENSATED — manual review required")

    print("\n  ACT 2 COMPLETE.\n")


def _comp_name(step: str) -> str:
    return {"reserve_inventory": "release_inventory"}.get(step, "compensator")


# ─────────────────────────────────────────────────────────────────────────────
# ACT 3 — Full Composition: Semantic Detection + Saga + State Sync
# ─────────────────────────────────────────────────────────────────────────────

class SearchPlannerTool(MCPToolContract):
    """Plans searches — intentionally buggy: emits paraphrased repeats."""
    name = "search_planner"
    version = "1.0.0"
    description = "Plans search queries for a research task."
    input_schema = ToolSchema(
        required=["topic"],
        properties={"topic": {"type": "string"}},
    )
    output_schema = ToolSchema(
        required=["queries"],
        properties={"queries": {"type": "array", "items": {"type": "string"}}},
    )
    def execute(self, inputs):
        t = inputs["topic"]
        # Bug: returns near-duplicate queries
        return {"queries": [
            f"{t} overview",
            f"overview of {t}",         # ← semantic duplicate
            f"{t} introduction guide",
        ]}


class ResultStoreTool(MCPToolContract):
    """Stores search results — side-effecting, compensatable."""
    name = "result_store"
    version = "1.0.0"
    description = "Persist search results to state store."
    input_schema = ToolSchema(
        required=["results"],
        properties={"results": {"type": "array", "items": {"type": "string"}}},
    )
    output_schema = ToolSchema(
        required=["stored"],
        properties={"stored": {"type": "boolean"}, "record_id": {"type": "string"}},
    )
    def __init__(self, store: InMemoryEventStore, agent_id: str):
        self._store = store
        self._agent_id = agent_id
        self._version = 0

    def execute(self, inputs):
        event = AgentEvent(
            agent_id=self._agent_id,
            event_type="results_stored",
            payload={"results": inputs["results"], "count": len(inputs["results"])},
            expected_version=self._version,
        )
        stored = self._store.append(event)
        self._version = stored.version
        return {"stored": True, "record_id": f"evt-v{stored.version}"}


class DeleteStoredResultsTool(MCPToolContract):
    """Compensator: deletes stored results from state store."""
    name = "delete_stored_results"
    version = "1.0.0"
    description = "Remove persisted search results — compensates ResultStore."
    input_schema = ToolSchema(required=[], properties={}, additional_properties=True)
    output_schema = ToolSchema(
        required=["deleted"],
        properties={"deleted": {"type": "boolean"}},
    )
    def execute(self, inputs):
        print("    ← DeleteStoredResults: removed results from state store")
        return {"deleted": True}


class SummaryGeneratorTool(MCPToolContract):
    """Generates summary — intentionally fails to trigger saga rollback."""
    name = "summary_generator"
    version = "1.0.0"
    description = "Generates a summary from results — fails in this demo."
    input_schema = ToolSchema(required=[], properties={}, additional_properties=True)
    output_schema = ToolSchema(required=[], properties={})
    def execute(self, inputs):
        raise RuntimeError("LLM context window exceeded — summary generation failed")


def act3_full_composition() -> None:
    _banner("ACT 3 — Full Composition: Semantic Detection + Saga + State Sync")

    print("""
  Scenario:
    A research pipeline with a buggy planner and a downstream failure:

      SearchPlanner  → emits paraphrased duplicate queries
      WebSearch      → CompositeLoopDetector catches the semantic repeat
      ResultStore    → writes to InMemoryEventStore (state sync)
      SummaryGen     → fails (LLM overload)
      Saga rolls back ResultStore → DeleteStoredResults compensator

    This is the complete production failure → detect → recover flow.
""")

    # Shared state store — visible to all agents
    event_store = InMemoryEventStore()
    result_store = ResultStoreTool(store=event_store, agent_id="research-pipeline")
    delete_tool = DeleteStoredResultsTool()

    # --- Part A: Semantic loop detection on the planner output ---------------
    print("  ── Part A: Semantic loop detection ──────────────────────────────")
    embedder = TFIDFEmbedder()
    detector = CompositeLoopDetector(
        max_repeats=1,
        semantic_threshold=0.80,
        embedder=embedder,
    )
    search_tool = WebSearchTool()

    planner_output = SearchPlannerTool().execute({"topic": "multi-agent orchestration"})
    queries = planner_output["queries"]
    print(f"  Planner emitted {len(queries)} queries: {queries}\n")

    safe_results = []
    semantic_loop_caught = False

    for query in queries:
        inputs = {"query": query}
        print(f"  Checking: {query!r}")
        _pause(60)
        try:
            detector.record(search_tool, inputs)
            result = search_tool.call(inputs)
            if isinstance(result, Ok):
                safe_results.extend(result.value["results"])
                print(f"    ✓ executed — {len(safe_results)} results accumulated")
        except (LoopError, SemanticLoopError) as exc:
            sim = f" (similarity={exc.similarity:.3f})" if isinstance(exc, SemanticLoopError) else ""
            print(f"    🔍  SEMANTIC LOOP DETECTED{sim} — '{query}' skipped ✓")
            LOGGER.book_pattern(
                "🔍  SEMANTIC LOOP DETECTED — paraphrased query caught before re-execution ✓",
                query=query,
            )
            semantic_loop_caught = True
            # Continue to next query rather than halt — safe to skip one duplicate

    print(f"\n  Semantic loop caught: {semantic_loop_caught}")
    print(f"  Safe results collected: {len(safe_results)}\n")

    # --- Part B: Saga with state sync ----------------------------------------
    print("  ── Part B: Saga with state sync + compensation ──────────────────")
    print("""
  Forward pass:
    Step 1: ResultStore  → writes to event store  (compensator: DeleteStoredResults)
    Step 2: SummaryGen   → fails (LLM overload)
    Rollback:
    Step 1 compensator   → DeleteStoredResults
""")

    saga = SagaOrchestrator()
    saga.add_step(SagaStep(
        tool=result_store,
        compensator=delete_tool,
    ))
    saga.add_step(SagaStep(
        tool=SummaryGeneratorTool(),
        compensator=None,
    ))

    result = saga.run(initial_inputs={"results": safe_results})

    print(f"\n  💸  SAGA STEP FAILED: {result.failed_at_step}")
    _pause(100)

    for step_name, comp_result in result.compensation_outcomes.items():
        if isinstance(comp_result, Ok):
            print(f"  ↩️   COMPENSATED: {step_name} ✓")
        else:
            print(f"  ✗   COMPENSATION FAILED: {step_name}")

    print()
    if result.fully_compensated:
        print("  ✅  SAGA FULLY COMPENSATED — no leaked resources ✓")

    # --- Part C: State store verification ------------------------------------
    print("\n  ── Part C: State store verification ─────────────────────────────")
    state = event_store.replay("research-pipeline")
    print(f"  Event store final state: {state if state else '{} (empty — compensation succeeded)'}")
    print(f"  Events logged: {event_store.current_version('research-pipeline')}")
    print("\n  ACT 3 COMPLETE.\n")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  Hero Demo — Multi-Agent Orchestration Reference             ║")
    print("║  Full failure → semantic detection → saga compensation       ║")
    print("║  Book: Aimal Khan & Shamvail Khan                            ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    act1_semantic_loop_detection()
    act2_saga_compensation()
    act3_full_composition()

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  All three acts completed.  Patterns demonstrated:           ║")
    print("║    Ch.15 — Semantic loop detection (TF-IDF + cosine sim)     ║")
    print("║    Ch.13 — Saga compensation (LIFO rollback, best-effort)    ║")
    print("║    Ch.12 — State sync via event store                        ║")
    print("║    Ch. 6 — Composite loop detection (exact + semantic)       ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()


if __name__ == "__main__":
    main()
