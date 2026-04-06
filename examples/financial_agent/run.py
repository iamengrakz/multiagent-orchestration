"""
examples/financial_agent/run.py
================================
Book reference: Chapters 10 and 11

A market data → risk model → portfolio rebalancer pipeline that demonstrates:

    default      — full pipeline run with token budget enforcement (Ch. 7, 11)
    --demo cb    — circuit breaker trips on market data failures (Ch. 10)

Run with zero external dependencies:

    python examples/financial_agent/run.py
    python examples/financial_agent/run.py --demo cb
    python examples/financial_agent/run.py --verbose

Expected output landmark (--demo cb):

    ⚡  CIRCUIT OPEN — market data tool failing; degraded response served ✓
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

from multiagent_orchestration.circuit_breaker import CircuitBreaker, CircuitOpenError
from multiagent_orchestration.contracts import MCPToolContract, ToolSchema
from multiagent_orchestration.dag import DirectedAcyclicGraph
from multiagent_orchestration.observability import StructuredLogger
from multiagent_orchestration.orchestrator import DAGOrchestrator, OrchestrationConfig
from multiagent_orchestration.result import Ok, Err
from multiagent_orchestration.token_budget import TokenBudgetManager, BudgetExceededError


# ===========================================================================
# Tool definitions
# ===========================================================================

class MarketDataTool(MCPToolContract):
    """Chapter 11 — fetches OHLCV data for a portfolio of symbols."""

    name = "market_data"
    version = "1.0.0"
    description = "Fetches current market prices and volume for given tickers."
    side_effecting = False

    input_schema = ToolSchema(
        required=["tickers"],
        properties={
            "tickers": {"type": "array", "items": {"type": "string"}},
            "period": {"type": "string", "default": "1d"},
        },
    )
    output_schema = ToolSchema(
        required=["prices"],
        properties={
            "prices": {
                "type": "object",
                "additionalProperties": {"type": "number"},
            }
        },
    )

    def __init__(self, should_fail: bool = False) -> None:
        self._should_fail = should_fail

    def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if self._should_fail:
            raise ConnectionError("Market data feed unavailable (simulated failure)")
        tickers = inputs.get("tickers", [])
        # Stub: replace with a real market data API call.
        prices = {ticker: 100.0 + hash(ticker) % 50 for ticker in tickers}
        return {"prices": prices}


class RiskModelTool(MCPToolContract):
    """Chapter 11 — computes Value-at-Risk for a set of positions."""

    name = "risk_model"
    version = "1.0.0"
    description = "Computes a simplified Value-at-Risk estimate for the portfolio."

    input_schema = ToolSchema(
        required=["prices"],
        properties={
            "prices": {
                "type": "object",
                "additionalProperties": {"type": "number"},
            }
        },
    )
    output_schema = ToolSchema(
        required=["var_95", "portfolio_value"],
        properties={
            "var_95": {"type": "number"},
            "portfolio_value": {"type": "number"},
            "risk_flags": {"type": "array", "items": {"type": "string"}},
        },
    )

    def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        prices = inputs.get("prices", {})
        portfolio_value = sum(prices.values())
        # Stub: simplified 5% VaR estimate.
        var_95 = portfolio_value * 0.05
        flags = ["HIGH_CONCENTRATION"] if len(prices) < 3 else []
        return {
            "var_95": round(var_95, 2),
            "portfolio_value": round(portfolio_value, 2),
            "risk_flags": flags,
        }


class RebalancerTool(MCPToolContract):
    """Chapter 11 — recommends rebalancing trades to reduce concentration risk."""

    name = "rebalancer"
    version = "1.0.0"
    description = "Generates trade recommendations to rebalance the portfolio."

    input_schema = ToolSchema(
        required=["var_95", "portfolio_value"],
        properties={
            "var_95": {"type": "number"},
            "portfolio_value": {"type": "number"},
            "risk_flags": {"type": "array", "items": {"type": "string"}},
        },
    )
    output_schema = ToolSchema(
        required=["recommendations"],
        properties={
            "recommendations": {"type": "array", "items": {"type": "string"}},
            "action_required": {"type": "boolean"},
        },
    )

    def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        flags = inputs.get("risk_flags", [])
        var = inputs.get("var_95", 0)
        pv = inputs.get("portfolio_value", 0)
        recs: list[str] = []
        if "HIGH_CONCENTRATION" in flags:
            recs.append("Diversify: add at least 2 uncorrelated positions.")
        if pv > 0 and var / pv > 0.08:
            recs.append("Reduce position sizes: VaR exceeds 8% of portfolio value.")
        if not recs:
            recs.append("Portfolio is within risk tolerance. No action required.")
        return {"recommendations": recs, "action_required": bool(flags)}


# ===========================================================================
# Demo runners
# ===========================================================================

TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]


def run_default(verbose: bool) -> None:
    """Chapter 11: full market-data → risk → rebalance pipeline."""
    print("\n" + "=" * 60)
    print("  DEMO: Financial Agent Pipeline  (Chapters 7, 11)")
    print("=" * 60)

    budget = TokenBudgetManager(
        pipeline_limit=20_000,
        per_agent_limits={"market_data": 3_000, "risk_model": 5_000, "rebalancer": 4_000},
    )

    dag = DirectedAcyclicGraph()
    market = MarketDataTool()
    risk = RiskModelTool()
    rebalancer = RebalancerTool()

    dag.add_edge(market, risk)
    dag.add_edge(risk, rebalancer)

    config = OrchestrationConfig(verbose=verbose)
    orchestrator = DAGOrchestrator(config=config)

    initial_inputs = {"market_data": {"tickers": TICKERS, "period": "1d"}}

    print(f"\n  Running pipeline for tickers: {TICKERS}")
    result = orchestrator.run(dag, initial_inputs=initial_inputs)

    if result.succeeded:
        rebalance_result = result.outputs.get("rebalancer")
        if rebalance_result and isinstance(rebalance_result, Ok):
            data = rebalance_result.value
            print("\n  Portfolio Recommendations:")
            for rec in data["recommendations"]:
                print(f"    • {rec}")
            print(f"\n  Action Required: {data['action_required']}")
    else:
        print(f"\n  Pipeline halted at: {result.halted_at}")

    remaining = budget.remaining("market_data")
    print(f"\n  Token budget — pipeline remaining: {remaining['pipeline']}")


def run_circuit_breaker_demo(verbose: bool) -> None:
    """Chapter 10: circuit breaker trips after repeated market data failures."""
    print("\n" + "=" * 60)
    print("  DEMO: Circuit Breaker  (Chapter 10)")
    print("=" * 60)
    print("  Scenario: market data feed is down; after 3 failures the")
    print("  circuit opens and subsequent calls are rejected immediately.\n")

    logger = StructuredLogger(verbose=verbose)
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
    failing_market = MarketDataTool(should_fail=True)
    inputs = {"tickers": TICKERS}

    for attempt in range(1, 6):
        print(f"  Attempt {attempt}: calling market_data …")
        result = cb.call(failing_market, inputs)
        if isinstance(result, Ok):
            print(f"    ✓ Success: {result.value}")
        elif isinstance(result.error, CircuitOpenError):
            logger.book_pattern(
                "⚡  CIRCUIT OPEN — market data tool failing; degraded response served ✓",
                attempt=attempt,
                retry_after=f"{result.error.retry_after:.1f}s",
                state=cb.state.value,
            )
            print(f"    Circuit is OPEN (state: {cb.state.value}). "
                  f"Serving cached/degraded data.")
            # In production: return last-known-good prices from a cache.
            degraded_prices = {t: 99.0 for t in TICKERS}
            print(f"    Degraded prices: {degraded_prices}")
            break
        else:
            print(f"    ✗ Tool error: {result.error}")
        print(f"    Circuit state: {cb.state.value}")


# ===========================================================================
# Entry point
# ===========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Financial Agent — companion example for Chapters 7, 10, 11"
    )
    parser.add_argument(
        "--demo",
        choices=["cb"],
        default=None,
        help="Run a specific pattern demo. 'cb' = circuit breaker (Ch. 10)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable structured JSON log output (Chapter 9 observability)",
    )
    args = parser.parse_args()

    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║  Financial Agent — Multi-Agent Orchestration Reference   ║")
    print("║  Book: Aimal Khan & Shamvail Khan                        ║")
    print("╚══════════════════════════════════════════════════════════╝")

    if args.demo == "cb":
        run_circuit_breaker_demo(args.verbose)
    else:
        run_default(args.verbose)

    print("\n  Done.\n")


if __name__ == "__main__":
    main()
