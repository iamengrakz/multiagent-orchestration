"""
tests/integration/test_financial_agent.py
Book reference: Chapters 10, 11
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples" / "financial_agent"))

import run as financial_run  # type: ignore[import]


class TestFinancialAgentDefault:
    def test_default_run_does_not_raise(self, capsys):
        financial_run.run_default(verbose=False)
        captured = capsys.readouterr()
        assert len(captured.out) > 0


class TestFinancialAgentCircuitBreaker:
    def test_cb_demo_emits_circuit_open(self, capsys):
        financial_run.run_circuit_breaker_demo(verbose=False)
        captured = capsys.readouterr()
        assert "CIRCUIT OPEN" in captured.err
