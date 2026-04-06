# Research Agent Example

Companion to **Chapters 5, 6, and 8** of
*Multi-Agent Orchestration in Action* — Aimal Khan & Shamvail Khan.

This single-file example demonstrates three production patterns using
**zero external dependencies** (stub LLM adapter, in-memory stores).

## What This Demonstrates

| Pattern | Chapter | CLI flag |
|---|:---:|---|
| Normal orchestration: planner → web_search → summarise → answer | 5 | *(default)* |
| Loop detection: same fingerprint caught before re-invocation | 6 | `--demo loop` |
| Idempotency: duplicate side-effect suppressed via SET-NX | 8 | `--demo idem` |

## Run It

```bash
# From repo root — all three patterns in sequence:
python examples/research_agent/run.py

# Custom research topic:
python examples/research_agent/run.py --query "transformer attention mechanisms 2025"

# Structured JSON logs (Chapter 9 observability):
python examples/research_agent/run.py --verbose

# Isolate a single pattern:
python examples/research_agent/run.py --demo loop   # 🔁  Chapter 6
python examples/research_agent/run.py --demo idem   # ♻️   Chapter 8

# Combine flags:
python examples/research_agent/run.py --demo loop --verbose
```

## Expected Output Landmarks

Both of these lines appear in the default (no `--demo`) run:

```
🔁  LOOP PREVENTED — orchestrator terminated before infinite tool call ✓
♻️   IDEMPOTENT RETRY HANDLED — duplicate email prevented ✓
```

In `--verbose` mode these are also emitted as NDJSON events tagged
`"tag": "BOOK_PATTERN"` — grep for that string in log aggregators.

## Swapping In Real Tools

Every tool in `run.py` is a concrete subclass of `MCPToolContract`.
To connect a real API, replace the `execute()` body:

```python
class WebSearchTool(MCPToolContract):
    # ... schema unchanged ...

    def execute(self, inputs: dict) -> dict:
        # Before: return {"results": ["[stub] ..."]}
        # After:
        results = my_search_client.search(inputs["search_terms"][0])
        return {"results": [r.snippet for r in results]}
```

The orchestrator, loop detector, and idempotency middleware require
**zero changes** — that is the point of the contract layer.

## Chapter Cross-References

- **Chapter 5, §5.3** — Building the four-tool DAG
- **Chapter 6, §6.2** — How `InvocationFingerprinter.record()` works
- **Chapter 8, §8.2** — How `IdempotencyMiddleware.call()` wraps `EmailDispatchTool`
- **Chapter 9, §9.2** — Structured log events emitted during this run
