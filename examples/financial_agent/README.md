# Financial Agent Example

Companion to **Chapters 7, 10, and 11** of
*Multi-Agent Orchestration in Action* — Aimal Khan & Shamvail Khan.

A complete market data → risk model → portfolio rebalancer pipeline
with token budget enforcement and circuit breaker protection.

## What This Demonstrates

| Pattern | Chapter | CLI flag |
|---|:---:|---|
| Full pipeline: market_data → risk_model → rebalancer | 7, 11 | *(default)* |
| Token budget enforcement before each LLM call | 7 | *(default)* |
| Circuit breaker: open after 3 failures, fast-fail thereafter | 10 | `--demo cb` |

## Run It

```bash
# Full pipeline (zero external dependencies):
python examples/financial_agent/run.py

# Circuit breaker demo (Chapter 10):
python examples/financial_agent/run.py --demo cb

# Structured JSON logs (Chapter 9):
python examples/financial_agent/run.py --verbose
python examples/financial_agent/run.py --demo cb --verbose
```

## Expected Output Landmark (`--demo cb`)

```
⚡  CIRCUIT OPEN — market data tool failing; degraded response served ✓
```

## Tool Pipeline

```
MarketDataTool
      │
      ▼ (prices dict)
RiskModelTool
      │
      ▼ (VaR, risk_flags)
RebalancerTool
      │
      ▼
Portfolio recommendations
```

## Chapter Cross-References

- **Chapter 7, §7.3** — Token budget reserve-then-reconcile pattern
- **Chapter 10, §10.4** — `CircuitBreaker` implementation walk-through
- **Chapter 10, §10.5** — Degraded response strategy (cached prices)
- **Chapter 11** — Full system walkthrough with all patterns composed
