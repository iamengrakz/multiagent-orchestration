# Contributing

Thank you for your interest in improving this reference implementation.
This repository is the production companion to the book
*Multi-Agent Orchestration in Action* by Aimal Khan and Shamvail Khan.
Every accepted change must preserve the direct correspondence between
the code and the book's chapter structure.

---

## What We Welcome

- **Bug fixes** — especially if a pattern implementation diverges from the
  book description.  Please cite the chapter, section, and page number in
  the Issue.
- **New adapter implementations** — a Google Gemini adapter, a local Ollama
  adapter, or an Azure OpenAI adapter following `LLMAdapter` (see
  `src/multiagent_orchestration/adapters/base.py`).
- **Test coverage improvements** — any module below 80% line coverage is a
  valid target.  Run `pytest --cov=src --cov-report=term-missing` to see gaps.
- **Diagram improvements** — corrections or additions to `docs/diagrams/`
  (Mermaid source files).
- **Documentation fixes** — typos, broken links, stale chapter references.

## What We Do Not Accept

- Changes that rename or restructure the public API of core library modules
  without a corresponding book update.  Open an Issue first to discuss.
- Example code that requires paid API keys to execute the **default**
  (no-flag) run.  All default paths must work with the stub adapter.
- New runtime dependencies that are not justified by a specific production
  pattern taught in the book.
- Publisher-specific branding of any kind.

---

## Development Setup

```bash
# 1. Fork and clone
git clone https://github.com/YOUR_USERNAME/multiagent-orchestration.git
cd multiagent-orchestration

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install in editable mode with all dev tools
pip install -e ".[dev]"
```

---

## Before Opening a Pull Request

All four checks must pass locally:

```bash
# Tests (unit + integration)
pytest -v

# Coverage (must stay >= 80%)
pytest --cov=src --cov-report=term-missing

# Type checking
mypy src/

# Linting and formatting
ruff check src/ examples/ tests/
black --check src/ examples/ tests/
```

To auto-fix formatting:

```bash
black src/ examples/ tests/
ruff check --fix src/ examples/ tests/
```

---

## Project Structure Quick Reference

| Path | Purpose |
|---|---|
| `src/multiagent_orchestration/` | Installable library — the patterns |
| `examples/research_agent/run.py` | Ch. 5/6/8 — single-file runnable example |
| `examples/financial_agent/run.py` | Ch. 10/11 — single-file runnable example |
| `tests/unit/` | Pure unit tests, no I/O |
| `tests/integration/` | End-to-end tests that import example `run.py` |
| `docs/diagrams/` | Mermaid source files |
| `ARCHITECTURAL_DECISIONS.md` | ADR log — read before proposing design changes |

---

## Commit Message Style

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(circuit_breaker): add half-open probe count metric
fix(idempotency): handle JSON decode error on stale sentinel
docs(adr): add ADR-009 for retry policy defaults
test(token_budget): add concurrency stress test
refactor(orchestrator): extract _run_single_tool helper
```

Scope is optional but encouraged.  Use the module name or `examples`,
`tests`, `docs`, `adr`, or `ci`.

---

## Reporting a Bug

Open an Issue with:

1. The chapter and section number the bug relates to.
2. The exact command you ran and the full output / traceback.
3. Your Python version (`python --version`) and OS.
4. What you expected to happen vs what actually happened.

---

## Adding a New LLM Adapter

1. Create `src/multiagent_orchestration/adapters/your_provider_adapter.py`.
2. Subclass `LLMAdapter` (see `adapters/base.py`).
3. Implement `complete()` and `model_name`.
4. Add the provider's SDK as an optional extra in `pyproject.toml`:
   ```toml
   [project.optional-dependencies]
   yourprovider = ["yourprovider-sdk>=1.0"]
   ```
5. Export the class from `adapters/__init__.py`.
6. Add a unit test in `tests/unit/test_your_provider_adapter.py` using
   `unittest.mock.patch` so no real API calls are made.
7. Document the new adapter in `README.md` under "Using a Real LLM Provider".

---

## Code of Conduct

Be respectful, constructive, and patient.  This is an educational repository
read by developers at all experience levels.  Assume good faith.
