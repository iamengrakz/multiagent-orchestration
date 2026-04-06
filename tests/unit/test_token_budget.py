"""
tests/unit/test_token_budget.py
Book reference: Chapter 7
"""

from __future__ import annotations

import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

import pytest

from multiagent_orchestration.token_budget import TokenBudgetManager, BudgetExceededError


class TestTokenBudgetManager:
    def test_reserve_within_agent_limit(self):
        budget = TokenBudgetManager(per_agent_limits={"agent_a": 1000})
        budget.reserve("agent_a", 500)  # should not raise

    def test_reserve_exceeds_agent_limit_raises(self):
        budget = TokenBudgetManager(per_agent_limits={"agent_a": 1000})
        with pytest.raises(BudgetExceededError) as exc_info:
            budget.reserve("agent_a", 1500)
        assert exc_info.value.limit_type == "agent"

    def test_reserve_within_pipeline_limit(self):
        budget = TokenBudgetManager(pipeline_limit=5000)
        budget.reserve("any_agent", 2000)  # should not raise

    def test_reserve_exceeds_pipeline_limit_raises(self):
        budget = TokenBudgetManager(pipeline_limit=1000)
        with pytest.raises(BudgetExceededError) as exc_info:
            budget.reserve("any_agent", 2000)
        assert exc_info.value.limit_type == "pipeline"

    def test_cumulative_reservations_across_agents(self):
        budget = TokenBudgetManager(pipeline_limit=500)
        budget.reserve("a", 200)
        budget.reserve("b", 200)
        with pytest.raises(BudgetExceededError):
            budget.reserve("c", 200)  # would total 600 > 500

    def test_remaining_with_no_limits(self):
        budget = TokenBudgetManager()
        remaining = budget.remaining("any_agent")
        assert remaining["agent"] is None
        assert remaining["pipeline"] is None

    def test_remaining_decreases_after_reserve(self):
        budget = TokenBudgetManager(
            pipeline_limit=1000,
            per_agent_limits={"a": 400},
        )
        budget.reserve("a", 100)
        r = budget.remaining("a")
        assert r["agent"] == 300
        assert r["pipeline"] == 900

    def test_reset_clears_usage(self):
        budget = TokenBudgetManager(
            pipeline_limit=1000,
            per_agent_limits={"a": 500},
        )
        budget.reserve("a", 400)
        budget.reset()
        r = budget.remaining("a")
        assert r["agent"] == 500
        assert r["pipeline"] == 1000

    def test_reconcile_adjusts_usage(self):
        budget = TokenBudgetManager(pipeline_limit=1000)
        budget.reserve("a", 300)   # estimated
        budget.reconcile("a", 250)  # actual was less
        assert budget.remaining("a")["pipeline"] == 750
