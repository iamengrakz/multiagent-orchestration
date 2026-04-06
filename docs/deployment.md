# Deployment Guide

**Book reference**: Chapter 12 — "Deploying Multi-Agent Systems to Production"

This guide covers every deployment path from local development through a
containerised production system.  Each section maps to a §12.x subsection
in the book.

---

## Chapter 12 Quick-Reference

| Section | Topic | This doc |
|:---:|---|---|
| 12.1 | Why deployment strategy matters for agentic systems | Introduction below |
| 12.2 | Local development workflow | [Local Development](#local-development) |
| 12.3 | Containerising with Docker | [Docker](#docker-single-container) |
| 12.4 | Security: non-root containers | [Dockerfile](../Dockerfile) |
| 12.5 | Full local stack with Redis | [Docker Compose](#docker-compose-with-redis) |
| 12.6 | Environment variable strategy | [Environment Variables](#environment-variables) |
| 12.7 | Switching idempotency stores | [Redis-backed Idempotency](#switching-to-redis-backed-idempotency) |
| 12.8 | Production hardening checklist | [Checklist](#production-hardening-checklist) |

---

## Local Development

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/multiagent-orchestration.git
cd multiagent-orchestration

# Isolated environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install library + dev extras
pip install -e ".[dev]"

# Verify — both examples should run with zero external deps
python examples/research_agent/run.py
python examples/financial_agent/run.py
```

---

## Docker (Single Container)

```bash
# Build the multi-stage image (builder + runtime)
docker build -t multiagent-orchestration:latest .

# Run research agent (default CMD)
docker run --rm multiagent-orchestration:latest

# Run financial agent with circuit breaker demo
docker run --rm multiagent-orchestration:latest \
    python examples/financial_agent/run.py --demo cb

# Run with a real OpenAI model
docker run --rm \
    -e ORCHESTRATION_LLM_ADAPTER=openai \
    -e OPENAI_API_KEY=sk-... \
    multiagent-orchestration:latest \
    python examples/research_agent/run.py --verbose
```

---

## Docker Compose (with Redis)

```bash
# Start the full stack (app + Redis)
docker-compose up

# Override the default command
docker-compose run app python examples/financial_agent/run.py --verbose

# Stop and clean up
docker-compose down

# Also remove the Redis data volume
docker-compose down -v
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `ORCHESTRATION_LLM_ADAPTER` | `stub` | Adapter selection: `stub` / `openai` / `anthropic` |
| `OPENAI_API_KEY` | — | Required when `ORCHESTRATION_LLM_ADAPTER=openai` |
| `OPENAI_API_BASE` | — | Optional; set for Azure OpenAI deployments |
| `ANTHROPIC_API_KEY` | — | Required when `ORCHESTRATION_LLM_ADAPTER=anthropic` |
| `REDIS_URL` | — | Redis connection string, e.g. `redis://localhost:6379/0` |

Create a `.env` file at the repo root (it is gitignored):

```bash
ORCHESTRATION_LLM_ADAPTER=openai
OPENAI_API_KEY=sk-...
```

---

## Switching to Redis-backed Idempotency

The default `InMemoryStore` is suitable for development and single-process
deployments.  For any multi-worker or multi-container setup, switch to
`RedisStore` (Chapter 8, §8.5):

```python
import os
import redis

from multiagent_orchestration.idempotency import RedisStore
from multiagent_orchestration.orchestrator import DAGOrchestrator, OrchestrationConfig

redis_client = redis.from_url(os.environ["REDIS_URL"])
store = RedisStore(redis_client, ttl_seconds=86_400)  # 24-hour key expiry

config = OrchestrationConfig(
    idempotency_store=store,
    max_loop_repeats=1,
    verbose=True,
)
orchestrator = DAGOrchestrator(config=config)
```

Install the Redis extra:

```bash
pip install "multiagent-orchestration[redis]"
```

---

## Switching to a Real LLM Adapter

### OpenAI

```bash
pip install "multiagent-orchestration[openai]"
export ORCHESTRATION_LLM_ADAPTER=openai
export OPENAI_API_KEY=sk-...
```

```python
from multiagent_orchestration.adapters.openai_adapter import OpenAIAdapter

adapter = OpenAIAdapter(model="gpt-4o")
```

### Anthropic Claude

```bash
pip install "multiagent-orchestration[anthropic]"
export ORCHESTRATION_LLM_ADAPTER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
```

```python
from multiagent_orchestration.adapters.anthropic_adapter import AnthropicAdapter

adapter = AnthropicAdapter(model="claude-sonnet-4-20250514")
```

Pass the adapter to any tool that needs LLM calls by replacing the stub
`execute()` body with a call to `adapter.complete(...)`.

---

## Production Hardening Checklist

Work through this checklist before directing real traffic to a deployment.
Each item references the book chapter that explains the rationale.

### Adapters & Secrets
- [ ] Replace `StubLLMAdapter` with a real adapter (`openai` or `anthropic`)
- [ ] Store API keys in environment variables or a secrets manager — never hardcoded
- [ ] Set `OPENAI_API_BASE` if using Azure OpenAI

### Idempotency
- [ ] Switch `InMemoryStore` → `RedisStore` for any multi-process setup (Ch. 8)
- [ ] Set a sensible `ttl_seconds` on `RedisStore` (24 hours is a good default)
- [ ] Confirm Redis is deployed with persistence (`appendonly yes` in redis.conf)

### Circuit Breaker (Ch. 10)
- [ ] Configure `failure_threshold` based on your tool's P99 error rate
- [ ] Configure `recovery_timeout` based on your downstream SLA
- [ ] Add a metrics export for `cb.state` (emit to Prometheus/Datadog/CloudWatch)
- [ ] Implement a degraded-response fallback for every `side_effecting=True` tool

### Token Budgets (Ch. 7)
- [ ] Set `pipeline_limit` based on your cost-per-run target
- [ ] Set per-agent limits for any tool whose prompt size varies with user input
- [ ] Wire actual token counts from LLM API responses into `budget.reconcile()`

### Observability (Ch. 9)
- [ ] Point `StructuredLogger(stream=...)` at your log aggregator's sink
- [ ] Add `trace_id` to all error alerts so individual runs are traceable
- [ ] Set up a dashboard on `event == "pipeline_end"` and `succeeded == false`

### Security
- [ ] Confirm the Docker image runs as non-root (already done in `Dockerfile`)
- [ ] Pin all dependency versions in `pyproject.toml` for reproducible builds
- [ ] Scan the image with `docker scout` or `trivy` before each release

### Operations
- [ ] Add a `/health` HTTP endpoint that returns `cb.state` for each critical tool
- [ ] Set up alerting on `event == "loop_detected"` (indicates a misbehaving planner)
- [ ] Set up alerting on `event == "budget_exceeded"` (indicates runaway cost)
- [ ] Document your rollback procedure if a new tool version breaks the pipeline
