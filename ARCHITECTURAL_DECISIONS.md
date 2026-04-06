# Architectural Decisions

Every non-obvious design choice in this repository is logged here as an
Architecture Decision Record (ADR).  Each ADR documents the context, the
decision, and the consequences.  Readers of the book will find corresponding
discussion in the chapters referenced.

---

## ADR-001 — `MCPToolContract` as an Abstract Base Class, Not a Protocol

**Status**: Accepted
**Book reference**: Chapter 2, §2.3

### Context

We needed a way to express the "tool contract" concept such that:
1. The orchestrator could iterate over tools polymorphically.
2. Tool authors could not accidentally skip implementing `execute()`.
3. Class-level attributes (`name`, `version`, `input_schema`, `output_schema`)
   were enforced at definition time, not at call time.

Python `Protocol` was considered but rejected because `Protocol` matching is
structural and cannot enforce class-level attribute presence at import time.
`abc.ABC` with `@abstractmethod` on `execute()` gives us the enforcement we
need, and the `__init_subclass__` hook (a future addition) can validate that
`name`, `version`, etc. are defined.

### Decision

`MCPToolContract` is a concrete `abc.ABC` subclass.  Tool authors inherit from
it.  The orchestrator accepts any `MCPToolContract` instance.

### Consequences

- (+) Missing `execute()` is caught at class definition, not at runtime.
- (+) Type checkers understand the inheritance hierarchy.
- (-) Cannot use structural subtyping; third-party tools must explicitly inherit.

---

## ADR-002 — Cycle Detection Runs Eagerly on `add_edge()`

**Status**: Accepted
**Book reference**: Chapter 4, §4.2

### Context

Cycles in the pipeline DAG are programming errors, not runtime conditions.
Two options were considered:

1. **Eager** — run DFS on every `add_edge()` call.
2. **Lazy** — run topological sort at execution time and raise then.

### Decision

Eager detection.  The DFS overhead on a typical pipeline (5–20 nodes) is
negligible, and surfacing the error at graph-construction time gives a far
better developer experience than a mysterious failure when the orchestrator
is first invoked.

### Consequences

- (+) Cycles are caught during unit tests of pipeline construction, not in
  integration tests or production.
- (-) `add_edge()` is slightly slower for large graphs (not a concern in
  practice — pipelines rarely exceed 50 nodes).

---

## ADR-003 — `Result[T, E]` Discriminated Union Over Exceptions

**Status**: Accepted
**Book reference**: Chapter 2, §2.5

### Context

Multi-agent pipelines have deep call stacks.  Using exceptions for control
flow makes it difficult to:
- Distinguish "expected failure" (tool returned an error) from "bug" (null
  pointer, key error).
- Write callers that handle partial failures without broad `except Exception`.
- Serialise failure information across process boundaries.

### Decision

All public APIs return `Ok[T] | Err[E]`.  Exceptions are caught inside
`MCPToolContract.call()` and wrapped in `Err`.  Only genuine programmer errors
(bugs) propagate as exceptions.

### Consequences

- (+) Callers are forced to handle both success and failure paths.
- (+) Failure information is a first-class data structure.
- (-) Slightly more verbose at call sites (must `match` or check `is_ok()`).

---

## ADR-004 — `InvocationFingerprinter` is Scoped Per Pipeline Run

**Status**: Accepted
**Book reference**: Chapter 6, §6.2

### Context

Should the loop detector maintain global state (across runs) or per-run state?

Global state would catch a tool being called identically across two separate
user requests — which is almost certainly not a loop.  It would also create
threading hazards in concurrent servers.

### Decision

`InvocationFingerprinter` instances are created fresh for each pipeline run
and discarded afterwards.  The orchestrator constructs one internally in
`DAGOrchestrator.run()`.

### Consequences

- (+) Thread-safe without locks (one instance per run).
- (+) No cross-run false positives.
- (-) Truly cross-run loops (same pipeline triggered twice by a runaway
  scheduler) are not detected — but that is the scheduler's responsibility,
  not the orchestrator's.

---

## ADR-005 — `InMemoryStore` is the Default Idempotency Backend

**Status**: Accepted
**Book reference**: Chapter 8, §8.4

### Context

The idempotency middleware needs a key-value store.  Redis is the production
choice but requires an external process.  We want the examples to run with
zero infrastructure.

### Decision

`InMemoryStore` (thread-safe dict + lock) is the default.  `RedisStore` is
provided as an opt-in via the `[redis]` extra.  The `IdempotencyStore`
abstract base makes swapping trivial (one line).

### Consequences

- (+) `python examples/research_agent/run.py` works with no Docker, no Redis.
- (-) `InMemoryStore` does not survive process restarts; document this clearly.

---

## ADR-006 — Circuit Breaker Does Not Wrap `call()`, Only `execute()`

**Status**: Accepted
**Book reference**: Chapter 10, §10.4

### Context

Should the circuit breaker sit *outside* `MCPToolContract.call()` (i.e., wrap
validation + execute) or *inside* (wrap only `execute()`)?

Wrapping `call()` means schema validation errors also increment the failure
counter — which is wrong.  A validation error is a programming error in the
calling code, not a tool availability problem.

### Decision

`CircuitBreaker.call(tool, inputs)` delegates to `tool.call(inputs)`.
Internally, `tool.call()` validates inputs first; only exceptions from
`execute()` reach the circuit breaker's failure counter.  Validation errors
wrapped in `Err(ValidationError)` are returned immediately by `tool.call()`
and the circuit breaker sees an `Err` — but we count only exceptions from
`execute()` as failures.

Actually, the current implementation counts any `Err` from `tool.call()` as a
failure.  This is a known simplification documented in Chapter 10, §10.6
("Limitations and Future Work").  A production system should distinguish
validation errors from availability errors before incrementing the counter.

### Consequences

- (+) Simple implementation; sufficient for the book's teaching goals.
- (-) Validation errors unfairly contribute to the failure count — noted as
  a production hardening step in Chapter 10.

---

## ADR-007 — Single-File Examples Over a Package Structure

**Status**: Accepted
**Book reference**: Chapter 5, §5.1

### Context

Each example could be a multi-file Python package (tools in one file,
orchestration logic in another, etc.) or a single `run.py`.

A package structure is more realistic for production, but it adds navigation
overhead for a reader following a chapter.  A single file lets the reader see
the entire example without leaving the file.

### Decision

Each example is a single `run.py` that is also directly runnable:
`python examples/research_agent/run.py`.

### Consequences

- (+) Reader can open one file and follow the chapter simultaneously.
- (+) No `__init__.py` or import path complexity within the example itself.
- (-) `run.py` is longer than it would be if split across files; acceptable
  given it is a teaching artefact, not a production codebase.

---

## ADR-008 — `StubLLMAdapter` Returns Deterministic Responses

**Status**: Accepted
**Book reference**: Chapter 7, §7.6

### Context

Examples that call a real LLM are expensive, slow, non-deterministic, and
require API keys.  All three of these properties make them unsuitable for:
- Continuous integration.
- Readers without API access.
- Reproducible book listings.

### Decision

All examples default to `StubLLMAdapter`, which returns configurable canned
strings matched by keyword.  Real adapters are opt-in via environment variable.

### Consequences

- (+) `pytest` passes with no network access and no API keys.
- (+) Example output is deterministic and matches the book listings exactly.
- (-) Readers must set `ORCHESTRATION_LLM_ADAPTER=openai` (or `anthropic`)
  and supply a key to see real LLM behaviour — clearly documented in README.

---

## ADR-009 — Event-Sourced State Store Uses Optimistic Concurrency, Not Locks

**Status**: Accepted
**Book reference**: Chapter 12, §12.9

### Context

Two design options existed for preventing state divergence in distributed agent
fleets: (a) pessimistic locking (acquire a lock before writing, release after)
or (b) optimistic concurrency (no lock; detect conflict at write time and retry).

Pessimistic locking is simpler to reason about but creates distributed lock
management overhead and deadlock risk.  Optimistic concurrency assumes conflicts
are rare (usually true for agent pipelines — typically one agent owns one state
stream) and handles them cleanly via `ConcurrentWriteError`.

### Decision

`InMemoryEventStore.append()` checks `expected_version == current_version`
atomically inside a per-agent lock before committing.  Callers that receive
`ConcurrentWriteError` reload state and retry (read-modify-append).

### Consequences

- (+) No distributed lock manager required.
- (+) `RedisEventStore` maps naturally to Redis `XADD` streams.
- (-) Callers must handle `ConcurrentWriteError` — documented in Chapter 12.

---

## ADR-010 — SemanticLoopDetector Uses a Sliding Window, Not a Full History Scan

**Status**: Accepted
**Book reference**: Chapter 15, §15.2

### Context

Semantic loop detection requires comparing each new invocation against previous
ones.  Comparing against the full run history is O(N × embedding_time) where N
grows unboundedly.

### Decision

`SemanticLoopDetector` maintains a fixed-size `deque` (default: 10 entries).
Only the last 10 invocations are compared against each new one.

The rationale: in a misbehaving pipeline, the semantic loop typically manifests
within 2–5 iterations.  A window of 10 catches it reliably while keeping
per-invocation cost bounded at O(window_size × embedding_time).

### Consequences

- (+) O(1) memory per pipeline run.
- (+) Latency per invocation is bounded regardless of pipeline length.
- (-) A loop that manifests after >10 unrelated calls would be missed — but
  this failure mode is not observed in practice and is noted in Chapter 15
  as a known limitation.

---

## ADR-011 — Saga Compensation Is Best-Effort, Not Transactional

**Status**: Accepted
**Book reference**: Chapter 13, §13.6

### Context

Should `SagaOrchestrator` halt the compensation chain if a compensator fails?

Option A: halt — simple, predictable, but leaves later steps uncompensated.
Option B: continue — more complex, but attempts maximum compensation.

### Decision

Compensation continues even when a compensator fails.  The failure is recorded
in `SagaResult.compensation_outcomes` and flagged as `Err`.  The
`fully_compensated` property lets callers check whether all compensations
succeeded.

The rationale: in distributed systems, "best-effort compensation" is the
standard because some compensators will fail (e.g. external API is down).
Halting early would leave more resources in an inconsistent state.

### Consequences

- (+) Maximum compensation attempted regardless of individual failures.
- (+) Caller can inspect `compensation_outcomes` and `uncompensated_steps`
  to decide on manual intervention.
- (-) The system can end up in a "partially compensated" state — documented
  in Chapter 13 as a known operational concern requiring monitoring.
