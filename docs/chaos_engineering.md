# Chaos Engineering Playbook

**Book reference**: Chapter 12 — "Production Resilience Testing"

> "Chaos engineering is the discipline of experimenting on a system in order
> to build confidence in the system's capability to withstand turbulent
> conditions in production."  
> — Principles of Chaos Engineering, Netflix

This playbook defines the specific failure scenarios to inject against the
production multi-agent orchestration stack, the expected system responses,
and how to confirm each resilience pattern is working correctly.

---

## Why Chaos Engineering for Agent Systems

Standard load tests and unit tests cannot reveal how an agent system behaves
when:

- An LLM API returns a 529 (overloaded) mid-pipeline
- The idempotency store loses connectivity between the SET-NX and the tool call
- A downstream tool hangs for 45 seconds instead of responding in 2
- The same pipeline is triggered twice simultaneously by a runaway scheduler
- A tool returns syntactically valid but semantically corrupted output

These scenarios require **deliberate fault injection** against a running system.

---

## Experiment Template

Every chaos experiment follows this structure:

```
Hypothesis:  When [fault condition], the system will [expected behaviour]
             without [unacceptable consequence].

Steady State: [metric or observable that confirms the system is healthy before injection]

Fault:        [specific failure to inject, how, and for how long]

Rollback:     [how to restore the system if the experiment goes wrong]

Observe:      [what to measure during and after injection]

Pass Criteria: [concrete threshold — e.g. "P99 latency stays below 2s", "no duplicate emails"]
```

---

## Experiment 1 — Circuit Breaker Trip Under Sustained Failure

**Hypothesis**: When `MarketDataTool` returns 5xx errors for 30 seconds, the
circuit breaker opens after 3 failures, all subsequent calls within the open
window return `CircuitOpenError` with zero tool execution, and the degraded
price cache is served within 200 ms.

**Steady State**: `financial_agent` pipeline completes in < 1s; `cb.state == CLOSED`

**Fault**: Inject `ConnectionError` into `MarketDataTool.execute()` by monkey-patching
or by routing the tool to a stub that always raises.

```python
# Fault injection — run this in a separate thread for 30 seconds
import time
original_execute = MarketDataTool.execute
MarketDataTool.execute = lambda self, inputs: (_ for _ in ()).throw(
    ConnectionError("chaos: injected failure")
)
time.sleep(30)
MarketDataTool.execute = original_execute
```

**Observe**:
- `circuit_breaker.state` transitions: CLOSED → OPEN (after 3 failures)
- `CircuitOpenError` raised for calls during OPEN window
- Degraded cache response time < 200 ms
- After `recovery_timeout`, state transitions to HALF_OPEN
- First successful probe closes the circuit again

**Pass Criteria**:
- [ ] `cb.state == OPEN` after exactly `failure_threshold` failures
- [ ] Zero `MarketDataTool.execute()` calls during OPEN window
- [ ] Degraded response served within 200 ms
- [ ] `⚡ CIRCUIT OPEN` log event appears in structured log

**Reference**: `examples/financial_agent/run.py --demo cb`

---

## Experiment 2 — Idempotency Under Concurrent Retry Storm

**Hypothesis**: When the orchestrator sends 10 concurrent retries of `EmailDispatchTool`
with the same idempotency key (simulating a timeout + retry storm), exactly 1
email is dispatched.

**Fault**:

```python
import concurrent.futures

store = InMemoryStore()
mw = IdempotencyMiddleware(store)
tool = EmailDispatchTool()
inputs = {"summary": "test", "recipient": "user@example.com"}
key = "chaos-email-001"

with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
    futures = [ex.submit(mw.call, tool, inputs, key) for _ in range(10)]
    results = [f.result() for f in futures]
```

**Observe**:
- `tool.call_count` after all futures complete
- Number of `Ok` results vs `Err` results

**Pass Criteria**:
- [ ] `tool.execute()` called exactly **1** time
- [ ] All 10 futures return `Ok` (subsequent calls return cached result)
- [ ] `♻️ IDEMPOTENT RETRY HANDLED` log event appears

---

## Experiment 3 — Loop Injection via Misbehaving Planner

**Hypothesis**: When `PlannerTool` is replaced with a stub that always emits
the same search query regardless of input, the `InvocationFingerprinter`
halts the pipeline at the second invocation of `WebSearchTool`.

**Fault**:

```python
class LoopingPlannerTool(MCPToolContract):
    name = "planner"
    # ... same schema as PlannerTool ...
    def execute(self, inputs):
        # Always returns the same output regardless of query:
        return {"search_terms": ["fixed query"], "original_query": "fixed query"}
```

**Observe**:
- `OrchestrationResult.halted_at`
- `OrchestrationResult.loop_errors` (should contain 1 fingerprint)
- `🔁 LOOP PREVENTED` log event

**Pass Criteria**:
- [ ] Pipeline halts at `web_search` on the second iteration
- [ ] `🔁 LOOP PREVENTED` log event appears in structured log
- [ ] No infinite loop or stack overflow

---

## Experiment 4 — Token Budget Exhaustion

**Hypothesis**: When cumulative token usage across agents approaches the
pipeline limit, `BudgetExceededError` is raised before the next LLM call
is made — not after.

**Fault**:

```python
budget = TokenBudgetManager(pipeline_limit=1_000)
budget.reserve("planner", 500)
budget.reserve("searcher", 400)
# Next reserve of 200 should raise before any LLM call:
budget.reserve("summariser", 200)  # 500+400+200 = 1100 > 1000
```

**Observe**: Exception is `BudgetExceededError` with `limit_type == "pipeline"`.

**Pass Criteria**:
- [ ] `BudgetExceededError` raised synchronously before tool execution
- [ ] No LLM API call is made when budget is exceeded
- [ ] `budget_exceeded` structured log event contains `agent_name` and `requested`

---

## Experiment 5 — State Divergence Under Concurrent Writers

**Hypothesis**: When two agents attempt to append events to the same state log
at the same expected version simultaneously, exactly one succeeds and the other
receives `ConcurrentWriteError`.

**Fault**:

```python
import concurrent.futures
from multiagent_orchestration.state_sync import InMemoryEventStore, AgentEvent, ConcurrentWriteError

store = InMemoryEventStore()
results = []

def write_event(query_text):
    try:
        e = store.append(AgentEvent(
            agent_id="shared_planner",
            event_type="query_set",
            payload={"query": query_text},
            expected_version=0,   # both writers think they're first
        ))
        results.append(("ok", e.version))
    except ConcurrentWriteError as ex:
        results.append(("conflict", ex))

with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
    ex.map(write_event, ["query A", "query B"])
```

**Observe**: `results` contains exactly one `"ok"` and one `"conflict"`.

**Pass Criteria**:
- [ ] Exactly 1 `"ok"` result
- [ ] Exactly 1 `ConcurrentWriteError`
- [ ] `store.current_version("shared_planner") == 1`

---

## Running the Full Playbook

```bash
# From repo root — all chaos experiments as a single pytest suite:
pytest tests/chaos/ -v

# Individual experiment:
pytest tests/chaos/test_circuit_breaker_chaos.py -v
pytest tests/chaos/test_idempotency_chaos.py -v
pytest tests/chaos/test_state_sync_chaos.py -v
```

> **Note**: `tests/chaos/` is intentionally not part of the standard CI run
> (`pytest tests/unit tests/integration`) because some experiments involve
> deliberate latency injection.  Run them separately against a staging environment.

---

## Interpreting Results

| Outcome | Meaning |
|---|---|
| All pass | The pattern implementations are resilient under the tested fault conditions |
| Circuit breaker opens too early | Reduce `failure_threshold` or check for false-positive exceptions |
| Idempotency allows duplicate | Check `set_if_absent` atomicity and `result_key` write ordering |
| Loop not detected | Verify fingerprint includes both `tool.name` and serialised inputs |
| State divergence not caught | Verify `expected_version` is checked inside the same lock as the append |
| Budget exhaustion too late | Verify `reserve()` is called before, not after, the LLM invocation |
