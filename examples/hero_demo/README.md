# Hero Demo

**The fastest way to see this framework's reliability guarantees in action.**

This single script walks through a complete failure scenario using four
production patterns in sequence — no API keys, no Docker, no configuration.

## What It Demonstrates

| Act | Pattern | Chapters |
|:---:|---|:---:|
| 1 | **Semantic loop detection** — a misbehaving planner issues paraphrased queries; `CompositeLoopDetector` catches the near-duplicate before it re-executes | 6, 15 |
| 2 | **Saga compensation** — a three-step order pipeline fails mid-way; `SagaOrchestrator` walks back in LIFO order and releases locked resources automatically | 13 |
| 3 | **Full composition** — semantic detection + saga + event-sourced state sync running together; demonstrates how the patterns compose in a realistic pipeline | 6, 12, 13, 15 |

## Run It

```bash
# From repo root:
python examples/hero_demo/run.py
```

## Expected Landmark Outputs

```
🔍  SEMANTIC LOOP DETECTED — paraphrased query caught before re-execution ✓
💸  SAGA STEP FAILED: charge_card — rolling back in LIFO order
↩️   COMPENSATED: reserve_inventory → release_inventory ✓
✅  SAGA FULLY COMPENSATED — no leaked resources ✓
```

## Key Files Featured

| File | Pattern |
|---|---|
| `src/multiagent_orchestration/semantic_loop_detector.py` | `TFIDFEmbedder`, `CompositeLoopDetector`, `SemanticLoopError` |
| `src/multiagent_orchestration/saga.py` | `SagaOrchestrator`, `SagaStep`, `SagaResult` |
| `src/multiagent_orchestration/state_sync/event_store.py` | `InMemoryEventStore`, `AgentEvent` |
| `src/multiagent_orchestration/loop_detector.py` | `InvocationFingerprinter`, `LoopError` |

## Chapter Cross-References

- **Chapter 6, §6.2** — `InvocationFingerprinter` exact SHA-256 fingerprinting
- **Chapter 13, §13.4** — `SagaOrchestrator` forward pass and compensation walk
- **Chapter 13, §13.6** — Best-effort compensation (continues on compensator failure)
- **Chapter 15, §15.2** — `SemanticLoopDetector` sliding-window cosine similarity
- **Chapter 15, §15.7** — `CompositeLoopDetector` layering exact + semantic checks
