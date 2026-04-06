"""
tests/unit/test_loop_detector.py
Book reference: Chapter 6
"""

from __future__ import annotations

import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

import pytest

from multiagent_orchestration.contracts import MCPToolContract, ToolSchema
from multiagent_orchestration.loop_detector import InvocationFingerprinter, LoopError


class PingTool(MCPToolContract):
    name = "ping"
    version = "1.0.0"
    description = "No-op test tool."
    input_schema = ToolSchema(required=[], properties={"key": {"type": "string"}})
    output_schema = ToolSchema(required=[], properties={})

    def execute(self, inputs):
        return {}


class TestInvocationFingerprinter:
    def setup_method(self):
        self.tool = PingTool()
        self.detector = InvocationFingerprinter(max_repeats=1)

    def test_first_call_succeeds(self):
        fp = self.detector.record(self.tool, {"key": "a"})
        assert isinstance(fp, str) and len(fp) == 64  # sha256 hex

    def test_different_inputs_do_not_trigger(self):
        self.detector.record(self.tool, {"key": "a"})
        self.detector.record(self.tool, {"key": "b"})  # different input — OK

    def test_repeated_identical_inputs_raise(self):
        self.detector.record(self.tool, {"key": "x"})
        with pytest.raises(LoopError) as exc_info:
            self.detector.record(self.tool, {"key": "x"})
        assert exc_info.value.tool_name == "ping"
        assert exc_info.value.occurrences == 2

    def test_max_repeats_two_allows_second(self):
        detector = InvocationFingerprinter(max_repeats=2)
        detector.record(self.tool, {"key": "y"})
        detector.record(self.tool, {"key": "y"})  # second — still OK
        with pytest.raises(LoopError):
            detector.record(self.tool, {"key": "y"})  # third — error

    def test_reset_clears_history(self):
        self.detector.record(self.tool, {"key": "z"})
        self.detector.reset()
        self.detector.record(self.tool, {"key": "z"})  # should not raise after reset

    def test_invalid_max_repeats_raises(self):
        with pytest.raises(ValueError):
            InvocationFingerprinter(max_repeats=0)

    def test_unique_invocations_count(self):
        self.detector.record(self.tool, {"key": "a"})
        self.detector.record(self.tool, {"key": "b"})
        assert self.detector.unique_invocations == 2

    def test_total_invocations_count(self):
        self.detector.record(self.tool, {"key": "a"})
        self.detector.record(self.tool, {"key": "b"})
        assert self.detector.total_invocations == 2
