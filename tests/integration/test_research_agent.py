"""
tests/integration/test_research_agent.py
Book reference: Chapters 5, 6, 8

End-to-end smoke tests for the research agent example.
These import and exercise run.py directly so they validate the
same code path a reader would use from the command line.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

# Make both the library and the example importable.
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples" / "research_agent"))

import run as research_run  # type: ignore[import]


class TestResearchAgentDefault:
    def test_default_run_does_not_raise(self, capsys):
        research_run.run_default(
            query="test query for integration", verbose=False
        )
        captured = capsys.readouterr()
        assert "ANSWER" in captured.out or len(captured.out) > 0


class TestResearchAgentLoopDemo:
    def test_loop_demo_emits_loop_prevented(self, capsys):
        research_run.run_loop_demo(
            query="infinite loop test", verbose=False
        )
        captured = capsys.readouterr()
        # The LOOP PREVENTED marker goes to stderr
        assert "LOOP PREVENTED" in captured.err


class TestResearchAgentIdemDemo:
    def test_idem_demo_emits_idempotent_handled(self, capsys):
        research_run.run_idem_demo(
            query="duplicate email test", verbose=False
        )
        captured = capsys.readouterr()
        assert "IDEMPOTENT RETRY HANDLED" in captured.err
