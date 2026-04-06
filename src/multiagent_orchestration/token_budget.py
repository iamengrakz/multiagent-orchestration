"""
token_budget.py — TokenBudgetManager
======================================
Book reference: Chapter 7, §7.1–7.4

Enforces token spending limits at two granularities:

- **Per-agent**: each tool invocation is charged against the agent's individual
  budget before the LLM call is made.
- **Per-pipeline**: a total budget is shared across all agents in a single run.

Both limits are checked *before* the LLM call — a speculative "reserve" — then
the actual usage is reconciled after the response arrives.

Book reference: Chapter 7, §7.3 — "Reserve-then-Reconcile Pattern"

Usage (Chapter 7, Listing 7.2)::

    budget = TokenBudgetManager(
        pipeline_limit=50_000,
        per_agent_limits={"planner": 5_000, "summariser": 10_000},
    )

    # Before LLM call:
    budget.reserve("planner", estimated_tokens=800)

    # After LLM call:
    budget.reconcile("planner", actual_tokens=743)

    # Query at any time:
    print(budget.remaining("planner"))
"""

from __future__ import annotations

import threading
from typing import Any


class BudgetExceededError(Exception):
    """Raised when a token reservation would exceed a configured limit.

    Book reference: Chapter 7, §7.2 — "Hard Limits vs Soft Warnings"

    Attributes:
        agent_name: Name of the agent that triggered the error.
        requested: Tokens being reserved.
        available: Tokens remaining at the time of the request.
        limit_type: ``"agent"`` or ``"pipeline"``.
    """

    def __init__(
        self,
        agent_name: str,
        requested: int,
        available: int,
        limit_type: str,
    ) -> None:
        self.agent_name = agent_name
        self.requested = requested
        self.available = available
        self.limit_type = limit_type
        super().__init__(
            f"Token budget exceeded ({limit_type} limit) for agent '{agent_name}': "
            f"requested {requested:,}, available {available:,}."
        )


class TokenBudgetManager:
    """Thread-safe token budget enforcer.

    Book reference: Chapter 7, §7.1 — "Why Token Budgets Matter"

    Args:
        pipeline_limit: Total tokens across all agents for one pipeline run.
            Set to ``None`` for no pipeline-level limit.
        per_agent_limits: Mapping of agent/tool name → individual token ceiling.
            Agents not listed here have no individual limit (still subject to
            the pipeline limit).
        warn_at_percent: Emit a structured log warning when remaining budget
            falls below this percentage.  Defaults to ``20``.
    """

    def __init__(
        self,
        pipeline_limit: int | None = None,
        per_agent_limits: dict[str, int] | None = None,
        warn_at_percent: int = 20,
    ) -> None:
        self._pipeline_limit = pipeline_limit
        self._per_agent_limits: dict[str, int] = per_agent_limits or {}
        self._warn_at_percent = warn_at_percent

        self._pipeline_used: int = 0
        self._agent_used: dict[str, int] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reserve(self, agent_name: str, estimated_tokens: int) -> None:
        """Speculatively reserve *estimated_tokens* before the LLM call.

        Args:
            agent_name: Identifier matching a key in ``per_agent_limits``.
            estimated_tokens: Best-guess token count (e.g. from a tokenizer).

        Raises:
            BudgetExceededError: If the reservation would breach any limit.
        """
        with self._lock:
            self._check_agent(agent_name, estimated_tokens)
            self._check_pipeline(agent_name, estimated_tokens)
            # Commit the reservation.
            self._agent_used[agent_name] = (
                self._agent_used.get(agent_name, 0) + estimated_tokens
            )
            self._pipeline_used += estimated_tokens

    def reconcile(self, agent_name: str, actual_tokens: int) -> None:
        """Correct the reservation with the actual token count post-response.

        Args:
            agent_name: Same identifier used in :meth:`reserve`.
            actual_tokens: Actual tokens reported by the LLM API response.
        """
        # In a real implementation, call reserve() with the difference.
        # Here we just replace to keep the example simple.
        with self._lock:
            previous = self._agent_used.get(agent_name, 0)
            delta = actual_tokens - previous
            self._agent_used[agent_name] = actual_tokens
            self._pipeline_used = max(0, self._pipeline_used + delta)

    def remaining(self, agent_name: str) -> dict[str, int | None]:
        """Return remaining budget for *agent_name* and the pipeline.

        Returns:
            Dict with keys ``"agent"`` and ``"pipeline"``, each mapping to
            the remaining token count or ``None`` if unlimited.
        """
        with self._lock:
            used = self._agent_used.get(agent_name, 0)
            agent_limit = self._per_agent_limits.get(agent_name)
            agent_remaining = (agent_limit - used) if agent_limit is not None else None
            pipeline_remaining = (
                (self._pipeline_limit - self._pipeline_used)
                if self._pipeline_limit is not None
                else None
            )
            return {"agent": agent_remaining, "pipeline": pipeline_remaining}

    def reset(self) -> None:
        """Reset all counters.  Call between pipeline runs."""
        with self._lock:
            self._pipeline_used = 0
            self._agent_used.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_agent(self, agent_name: str, requested: int) -> None:
        limit = self._per_agent_limits.get(agent_name)
        if limit is None:
            return
        used = self._agent_used.get(agent_name, 0)
        available = limit - used
        if requested > available:
            raise BudgetExceededError(agent_name, requested, available, "agent")

    def _check_pipeline(self, agent_name: str, requested: int) -> None:
        if self._pipeline_limit is None:
            return
        available = self._pipeline_limit - self._pipeline_used
        if requested > available:
            raise BudgetExceededError(agent_name, requested, available, "pipeline")
