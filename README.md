# Multi-Agent Orchestration: Production Reference Implementation

> **📘 Official Companion Repository**
> This is the production reference implementation for the book
> **"Multi-Agent Orchestration in Action: MCP Contracts · DAG Orchestration · Production Resilience"**
> by **Aimal Khan** (Lead Author) and **Shamvail Khan** (Co-Author).
> Every pattern, class, and runnable example maps directly to a chapter in the book.

---

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Type checked: mypy](https://img.shields.io/badge/type%20checked-mypy-blue)](https://mypy-lang.org/)
[![Tests](https://img.shields.io/badge/tests-pytest-orange)](https://docs.pytest.org/)
[![CI](https://github.com/iamengrakz/multiagent-orchestration/actions/workflows/ci.yml/badge.svg)](https://github.com/iamengrakz/multiagent-orchestration/actions)

---

## Proof of Authority: Run It In 60 Seconds

```bash
git clone https://github.com/iamengrakz/multiagent-orchestration.git
cd multiagent-orchestration
pip install -e ".[dev]"
python examples/research_agent/run.py
```

You will see three production patterns fire in sequence:

```
🔁  LOOP PREVENTED — orchestrator terminated before infinite tool call ✓
♻️   IDEMPOTENT RETRY HANDLED — duplicate email prevented ✓
```

```bash
python examples/financial_agent/run.py --demo cb
```
```
⚡  CIRCUIT OPEN — market data tool failing; degraded response served ✓
```

---

## Key Production Patterns

| Pattern | Module | What It Solves |
|---|---|---|
| **`MCPToolContract`** | `contracts.py` | Typed, versioned, schema-validated tool contracts; decouples tool authors from the orchestrator |
| **DAG Orchestrator** | `orchestrator.py` | Topological execution with upstream-output propagation; halts cleanly on first error |
| **Loop Detection** | `loop_detector.py` | SHA-256 fingerprinting of `(tool, args)`; halts re-invocation before it recurses |
| **Idempotency Middleware** | `idempotency.py` | Two-key SET-NX pattern (lock key + result key) guards side-effecting calls; Redis adapter included |
| **Token Budget Manager** | `token_budget.py` | Per-agent and per-pipeline token ceilings enforced *before* LLM calls; reserve-then-reconcile |
| **Circuit Breaker** | `circuit_breaker.py` | Half-open / open / closed state machine; thread-safe, configurable per tool |
| **Structured Observability** | `observability.py` | NDJSON event stream with `span_id`, `trace_id`, `BOOK_PATTERN` tags; drops into any collector |
| **Retry & Back-off** | `retry.py` | Exponential back-off with jitter; configurable per contract |
| **Result Envelope** | `result.py` | `Ok`/`Err` discriminated union propagated through the full call graph |
| **Pluggable LLM Adapter** | `adapters/` | Swap OpenAI, Anthropic, or Ollama without touching orchestration logic |
| **Event-Sourced State Sync** | `state_sync/` | Append-only event log with optimistic concurrency + exactly-once delivery for distributed fleets |
| **Human-in-the-Loop Escalation** | `human_in_the_loop.py` | Four-tier ladder (AUTO → REVIEW → OVERRIDE → ABORT) with composable rules + pluggable gateway |

---

## Chapter-to-Code Mapping

| Chapter | Title | Key Source Files | Runnable Demo |
|:---:|---|---|---|
| 1 | The Multi-Agent Landscape | `contracts.py` intro | — |
| 2 | Designing Tool Contracts with MCP | `contracts.py`, `result.py` | — |
| 3 | Schema Validation and Versioning | `contracts.py`, `_validator.py` | `tests/unit/test_contracts.py` |
| 4 | Building a DAG Orchestrator | `orchestrator.py`, `dag.py` | `tests/unit/test_dag.py` |
| 5 | Wiring Agents: Planner → Worker → Synthesiser | `orchestrator.py` | `python examples/research_agent/run.py` |
| 6 | Loop Detection and Cycle Prevention | `loop_detector.py` | `python examples/research_agent/run.py --demo loop` |
| 7 | Token Budget Management | `token_budget.py`, `adapters/` | `python examples/financial_agent/run.py` |
| 8 | Idempotency: Safe Retries and Duplicate Suppression | `idempotency.py` | `python examples/research_agent/run.py --demo idem` |
| 9 | Observability and Structured Tracing | `observability.py` | `--verbose` flag on any example |
| 10 | Circuit Breakers and Graceful Degradation | `circuit_breaker.py` | `python examples/financial_agent/run.py --demo cb` |
| 11 | Human-in-the-Loop Escalation | `human_in_the_loop.py` | `tests/unit/test_human_in_the_loop.py` |
| 12 | Distributed State and Production Deployment | `state_sync/`, `docs/deployment.md`, `docs/chaos_engineering.md` | `tests/unit/test_state_sync.py` |

---

## Repository Structure

```
multiagent-orchestration/
├── README.md
├── ARCHITECTURAL_DECISIONS.md     ← ADR log for every non-obvious design choice (8 ADRs)
├── CONTRIBUTING.md
├── LICENSE                        ← MIT
├── pyproject.toml                 ← zero external runtime deps in core
├── Dockerfile                     ← multi-stage production image
├── docker-compose.yml             ← app + Redis local stack
│
├── src/
│   └── multiagent_orchestration/
│       ├── contracts.py           ← MCPToolContract, ToolSchema, ValidationError
│       ├── dag.py                 ← DirectedAcyclicGraph, CycleError
│       ├── orchestrator.py        ← DAGOrchestrator, OrchestrationConfig
│       ├── loop_detector.py       ← InvocationFingerprinter, LoopError
│       ├── idempotency.py         ← IdempotencyMiddleware, InMemoryStore, RedisStore
│       ├── token_budget.py        ← TokenBudgetManager, BudgetExceededError
│       ├── circuit_breaker.py     ← CircuitBreaker, CircuitState, CircuitOpenError
│       ├── observability.py       ← StructuredLogger, Span (NDJSON events)
│       ├── retry.py               ← RetryPolicy, with_retry (exp. back-off + jitter)
│       ├── result.py              ← Ok, Err, Result (discriminated union)
│       ├── human_in_the_loop.py   ← HumanInTheLoop, four-tier EscalationPolicy
│       ├── _validator.py          ← stdlib-only JSON Schema validator (zero deps)
│       ├── state_sync/
│       │   └── event_store.py     ← InMemoryEventStore, RedisEventStore, AgentEvent
│       └── adapters/
│           ├── stub_adapter.py    ← StubLLMAdapter (zero deps, deterministic)
│           ├── openai_adapter.py
│           └── anthropic_adapter.py
│
├── examples/
│   ├── research_agent/run.py      ← Chapters 5, 6, 8 — fully runnable
│   └── financial_agent/run.py     ← Chapters 7, 10, 11 — fully runnable
│
├── tests/
│   ├── unit/                      ← 8 modules, 70+ assertions, zero network calls
│   └── integration/               ← end-to-end: verifies all 3 landmark outputs
│
└── docs/
    ├── deployment.md              ← Ch. 12 production checklist
    ├── chaos_engineering.md       ← 5 chaos experiments with pass/fail criteria
    └── diagrams/                  ← 4 Mermaid diagrams (render at mermaid.live)
```

---

## Architectural Highlights for Technical Reviewers

### Zero External Runtime Dependencies

The core library imports nothing outside the Python stdlib.  `_validator.py`
provides a JSON Schema validator for the keyword subset used by `ToolSchema`.
Full Draft-7 compliance is available via `pip install ".[jsonschema]"` +
`MULTIAGENT_USE_JSONSCHEMA=1`.  This means the library installs cleanly in
air-gapped environments and never conflicts with existing dependency trees.

### Idempotency: Two-Key SET-NX Pattern

The most dangerous race condition in a retried pipeline: tool executes
successfully, then the process crashes before the result is cached.  On the
next retry the side effect fires again.  The middleware prevents this:

```python
# Phase 1 — check for a previously completed result
existing = self._store.get(result_key)
if existing is not None:
    return Ok(json.loads(existing))    # cached — tool.execute() never called again

# Phase 2 — claim the lock key (SET-NX)
self._store.set_if_absent(key, sentinel)

# Phase 3 — execute and write result key
result = tool.call(inputs)
if isinstance(result, Ok):
    self._store.set_if_absent(result_key, json.dumps(result.value))
```

### Event-Sourced State Synchronisation

Two agents in different threads (or regions) updating shared world state is the
root cause of most distributed agent failures.  `InMemoryEventStore` enforces:

- **Optimistic concurrency**: every `append()` declares `expected_version`; a
  `ConcurrentWriteError` is raised if the log has advanced since the writer last read.
- **Exactly-once delivery**: each `AgentEvent` carries a UUID `event_id` that the
  store deduplicates — a retry storm cannot insert the same event twice.
- **Replay projection**: `store.replay(agent_id)` reconstructs current state by
  folding event payloads in version order — no shared mutable state required.

### Human-in-the-Loop Escalation Ladder

The four-tier model (AUTO / REVIEW / OVERRIDE / ABORT) composes from any
combination of `HighCostRule`, `SensitiveActionRule`, and `CustomRule`.  The
policy evaluates all rules and returns the highest-priority tier.  The
`HumanGateway` abstraction keeps the handoff mechanism (Slack, email, webhook)
swappable without changing any orchestration logic.

---

## Running Tests

```bash
pytest                                          # full suite
pytest tests/unit -v                            # verbose unit tests
pytest --cov=src --cov-report=term-missing      # coverage report
```

---

## Using a Real LLM Provider

```bash
export ORCHESTRATION_LLM_ADAPTER=openai
export OPENAI_API_KEY=sk-...
python examples/research_agent/run.py           # no other changes needed
```

---

## Docker

```bash
docker build -t multiagent-orchestration:latest .
docker run --rm multiagent-orchestration:latest
docker-compose up                               # + Redis-backed idempotency
```

---

## About the Authors

**Aimal Khan** (Lead Author) is a software engineer and educator at SST IT,
Government Elementary and Secondary Department, Khyber Pakhtunkhwa, Pakistan.
He builds production-grade AI systems for real-world deployment in
resource-constrained environments, specialising in agentic architectures,
multi-agent orchestration, and practical LLM engineering.

**Shamvail Khan** (Co-Author) is a Computer Science student at the University
of Engineering and Technology Peshawar. He contributed to the circuit breaker
module, financial agent example, structured observability layer, and distributed
state synchronisation design.

---

## License

Released under the [MIT License](LICENSE). Book text is separately copyrighted.

---

*Found a bug? Open an [Issue](../../issues).
PRs improving test coverage or adding adapter implementations are welcome —
see [CONTRIBUTING.md](CONTRIBUTING.md).*
