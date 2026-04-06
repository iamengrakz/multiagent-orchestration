# Multi-stage production Docker image
# Book reference: Chapter 12 — "Deploying Multi-Agent Systems to Production"
#
# Build:
#   docker build -t multiagent-orchestration:latest .
#
# Run research agent (default):
#   docker run --rm multiagent-orchestration:latest
#
# Run financial agent:
#   docker run --rm multiagent-orchestration:latest \
#     python examples/financial_agent/run.py --demo cb
#
# Run with a real LLM provider:
#   docker run --rm \
#     -e ORCHESTRATION_LLM_ADAPTER=openai \
#     -e OPENAI_API_KEY=sk-... \
#     multiagent-orchestration:latest

# ── Stage 1: builder ──────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Copy only what's needed to build the wheel
COPY pyproject.toml .
COPY src/ src/

# Build the wheel; no network calls at runtime
RUN pip install --no-cache-dir build && \
    python -m build --wheel --outdir /dist

# ── Stage 2: runtime ──────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="Multi-Agent Orchestration Reference"
LABEL org.opencontainers.image.description="Production companion to the book by Aimal Khan & Shamvail Khan"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.source="https://github.com/YOUR_USERNAME/multiagent-orchestration"

WORKDIR /app

# Install the library wheel (no build tools in runtime image)
COPY --from=builder /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl

# Copy examples (not part of the installable wheel)
COPY examples/ examples/

# Non-root user — principle of least privilege (Chapter 12, §12.4)
RUN adduser --disabled-password --gecos "" --uid 1001 appuser && \
    chown -R appuser:appuser /app
USER appuser

# Healthcheck: verify the library is importable
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import multiagent_orchestration; print('ok')"

# Default: run the research agent in verbose mode
CMD ["python", "examples/research_agent/run.py", "--verbose"]
