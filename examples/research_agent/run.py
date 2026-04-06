"""
examples/research_agent/run.py
================================
Book reference: Chapters 5, 6, and 8

A complete, self-contained multi-agent research pipeline that demonstrates
three production patterns from the book:

    default  — planner → web_search → summarise → answer  (Chapter 5)
    --demo loop  — loop detection halts an infinite re-search cycle (Chapter 6)
    --demo idem  — idempotency middleware prevents a duplicate email send (Chapter 8)

Run with zero external dependencies (stub LLM adapter):

    python examples/research_agent/run.py
    python examples/research_agent/run.py --query "transformer attention 2025"
    python examples/research_agent/run.py --demo loop
    python examples/research_agent/run.py --demo idem
    python examples/research_agent/run.py --verbose

Expected output landmarks (both appear in the default run):

    🔁  LOOP PREVENTED — orchestrator terminated before infinite tool call ✓
    ♻️   IDEMPOTENT RETRY HANDLED — duplicate email prevented ✓

In --verbose mode every event carries "tag": "BOOK_PATTERN" for easy grepping.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Make the library importable when running from repo root without installation
# ---------------------------------------------------------------------------
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

from multiagent_orchestration.contracts import MCPToolContract, ToolSchema
from multiagent_orchestration.dag import DirectedAcyclicGraph
from multiagent_orchestration.idempotency import IdempotencyMiddleware, InMemoryStore
from multiagent_orchestration.loop_detector import InvocationFingerprinter, LoopError
from multiagent_orchestration.observability import StructuredLogger
from multiagent_orchestration.orchestrator import DAGOrchestrator, OrchestrationConfig
from multiagent_orchestration.result import Ok, Err


# ===========================================================================
# Tool definitions
# ===========================================================================

class PlannerTool(MCPToolContract):
    """Chapter 5 — breaks a user query into a search plan."""

    name = "planner"
    version = "1.0.0"
    description = "Decomposes a research query into actionable search terms."
    input_schema = ToolSchema(
        required=["query"],
        properties={"query": {"type": "string", "minLength": 1}},
    )
    output_schema = ToolSchema(
        required=["search_terms"],
        properties={
            "search_terms": {"type": "array", "items": {"type": "string"}},
            "original_query": {"type": "string"},
        },
    )

    def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        query = inputs["query"]
        # Stub: in production, call an LLM adapter here.
        terms = [query, f"{query} overview", f"{query} 2025"]
        return {"search_terms": terms, "original_query": query}


class WebSearchTool(MCPToolContract):
    """Chapter 5 — searches the web; Chapter 6 — subject of loop detection."""

    name = "web_search"
    version = "1.0.0"
    description = "Executes a web search and returns ranked result snippets."
    input_schema = ToolSchema(
        required=["search_terms"],
        properties={
            "search_terms": {"type": "array", "items": {"type": "string"}},
            "original_query": {"type": "string"},
        },
    )
    output_schema = ToolSchema(
        required=["results"],
        properties={
            "results": {"type": "array", "items": {"type": "string"}},
            "query_used": {"type": "string"},
        },
    )

    def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        terms = inputs.get("search_terms", [])
        query = terms[0] if terms else "unknown"
        # Stub: replace with a real search API call.
        snippets = [
            f"[stub] Result 1 for '{query}': Recent advances in the field…",
            f"[stub] Result 2 for '{query}': A survey of methods published…",
            f"[stub] Result 3 for '{query}': Industry adoption patterns show…",
        ]
        return {"results": snippets, "query_used": query}


class SummariseTool(MCPToolContract):
    """Chapter 5 — synthesises search results into a coherent summary."""

    name = "summarise"
    version = "1.0.0"
    description = "Synthesises raw search results into a structured summary."
    input_schema = ToolSchema(
        required=["results"],
        properties={
            "results": {"type": "array", "items": {"type": "string"}},
            "query_used": {"type": "string"},
        },
    )
    output_schema = ToolSchema(
        required=["summary"],
        properties={"summary": {"type": "string"}},
    )

    def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        count = len(inputs.get("results", []))
        query = inputs.get("query_used", "the topic")
        # Stub: replace with an LLM adapter call.
        summary = (
            f"[stub] Synthesised summary of {count} result(s) on '{query}': "
            f"The literature highlights three main themes — scalability, "
            f"interpretability, and real-world deployment considerations."
        )
        return {"summary": summary}


class AnswerTool(MCPToolContract):
    """Chapter 5 — formats the final answer for the end user."""

    name = "answer"
    version = "1.0.0"
    description = "Formats the synthesised summary as a final user-facing answer."
    input_schema = ToolSchema(
        required=["summary"],
        properties={"summary": {"type": "string"}},
    )
    output_schema = ToolSchema(
        required=["answer"],
        properties={"answer": {"type": "string"}},
    )

    def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {"answer": f"ANSWER: {inputs['summary']}"}


class EmailDispatchTool(MCPToolContract):
    """Chapter 8 — side-effecting tool guarded by idempotency middleware."""

    name = "email_dispatch"
    version = "1.0.0"
    description = "Sends the research summary by email (side-effecting)."
    side_effecting = True
    idempotent = True

    input_schema = ToolSchema(
        required=["summary"],
        properties={
            "summary": {"type": "string"},
            "recipient": {"type": "string"},
        },
    )
    output_schema = ToolSchema(
        required=["sent"],
        properties={
            "sent": {"type": "boolean"},
            "message_id": {"type": "string"},
        },
    )

    def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        recipient = inputs.get("recipient", "user@example.com")
        print(f"  [email_dispatch] Sending to {recipient}… (stub — no real email sent)")
        return {"sent": True, "message_id": "stub-msg-001"}


# ===========================================================================
# Demo runners
# ===========================================================================

def run_default(query: str, verbose: bool) -> None:
    """Chapter 5: normal planner → search → summarise → answer pipeline."""
    print("\n" + "=" * 60)
    print("  DEMO: Normal Research Pipeline  (Chapter 5)")
    print("=" * 60)

    dag = DirectedAcyclicGraph()
    planner = PlannerTool()
    searcher = WebSearchTool()
    summariser = SummariseTool()
    answerer = AnswerTool()

    dag.add_edge(planner, searcher)
    dag.add_edge(searcher, summariser)
    dag.add_edge(summariser, answerer)

    config = OrchestrationConfig(verbose=verbose)
    orchestrator = DAGOrchestrator(config=config)
    result = orchestrator.run(dag, initial_inputs={"planner": {"query": query}})

    if result.succeeded:
        answer = result.outputs.get("answer")
        if answer and isinstance(answer, Ok):
            print(f"\n  {answer.value['answer']}\n")
    else:
        print(f"\n  Pipeline halted at: {result.halted_at}\n")


def run_loop_demo(query: str, verbose: bool) -> None:
    """Chapter 6: demonstrates loop detection preventing an infinite cycle."""
    print("\n" + "=" * 60)
    print("  DEMO: Loop Detection  (Chapter 6)")
    print("=" * 60)
    print("  Scenario: a misbehaving planner re-emits the same search query.")
    print("  The InvocationFingerprinter catches it before the second call.\n")

    logger = StructuredLogger(verbose=verbose)
    detector = InvocationFingerprinter(max_repeats=1)
    searcher = WebSearchTool()

    # Simulate the orchestrator calling web_search twice with identical args.
    calls = [
        {"search_terms": [query], "original_query": query},
        {"search_terms": [query], "original_query": query},  # duplicate
    ]

    for i, inputs in enumerate(calls, start=1):
        print(f"  Attempt {i}: invoking '{searcher.name}' …")
        try:
            fp = detector.record(searcher, inputs)
            result = searcher.call(inputs)
            print(f"    ✓ call succeeded  (fingerprint: {fp[:12]}…)")
        except LoopError as exc:
            logger.book_pattern(
                "🔁  LOOP PREVENTED — orchestrator terminated before infinite tool call ✓",
                fingerprint=exc.fingerprint,
                occurrences=exc.occurrences,
            )
            break


def run_idem_demo(query: str, verbose: bool) -> None:
    """Chapter 8: demonstrates idempotency suppressing a duplicate email send."""
    print("\n" + "=" * 60)
    print("  DEMO: Idempotency Middleware  (Chapter 8)")
    print("=" * 60)
    print("  Scenario: the orchestrator retries after a transient timeout.")
    print("  The InMemoryStore SET-NX prevents a second email being sent.\n")

    logger = StructuredLogger(verbose=verbose)
    store = InMemoryStore()
    middleware = IdempotencyMiddleware(store)
    email_tool = EmailDispatchTool()

    summary = f"Research summary for '{query}': [stub content]"
    inputs = {"summary": summary, "recipient": "reader@example.com"}
    key = "send-research-summary-001"

    for attempt in range(1, 3):
        print(f"  Attempt {attempt}: calling email_dispatch …")
        result = middleware.call(email_tool, inputs, idempotency_key=key)
        if isinstance(result, Ok):
            if attempt == 1:
                print(f"    ✓ Email sent  (message_id: {result.value['message_id']})")
            else:
                logger.book_pattern(
                    "♻️   IDEMPOTENT RETRY HANDLED — duplicate email prevented ✓",
                    key=key,
                    attempt=attempt,
                )
        else:
            print(f"    ✗ Error: {result.error}")


# ===========================================================================
# Entry point
# ===========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Research Agent — companion example for Chapters 5, 6, 8"
    )
    parser.add_argument(
        "--query",
        default="multi-agent orchestration patterns",
        help="Research topic (default: 'multi-agent orchestration patterns')",
    )
    parser.add_argument(
        "--demo",
        choices=["loop", "idem"],
        default=None,
        help="Run a specific pattern demo (default: runs all three in sequence)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable structured JSON log output (Chapter 9 observability)",
    )
    args = parser.parse_args()

    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║  Research Agent — Multi-Agent Orchestration Reference    ║")
    print("║  Book: Aimal Khan & Shamvail Khan                        ║")
    print("╚══════════════════════════════════════════════════════════╝")

    if args.demo == "loop":
        run_loop_demo(args.query, args.verbose)
    elif args.demo == "idem":
        run_idem_demo(args.query, args.verbose)
    else:
        # Default: run all three patterns in sequence.
        run_default(args.query, args.verbose)
        run_loop_demo(args.query, args.verbose)
        run_idem_demo(args.query, args.verbose)

    print("\n  Done.\n")


if __name__ == "__main__":
    main()
