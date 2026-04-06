"""
tests/unit/test_circuit_breaker.py
Book reference: Chapter 10
"""

from __future__ import annotations

import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

import time

from multiagent_orchestration.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)
from multiagent_orchestration.contracts import MCPToolContract, ToolSchema
from multiagent_orchestration.result import Ok, Err


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class SucceedingTool(MCPToolContract):
    name = "succeed"
    version = "1.0.0"
    description = "Always succeeds."
    input_schema = ToolSchema(required=[], properties={})
    output_schema = ToolSchema(required=["ok"], properties={"ok": {"type": "boolean"}})

    def execute(self, inputs):
        return {"ok": True}


class FailingTool(MCPToolContract):
    name = "fail"
    version = "1.0.0"
    description = "Always fails."
    input_schema = ToolSchema(required=[], properties={})
    output_schema = ToolSchema(required=[], properties={})

    def execute(self, inputs):
        raise RuntimeError("simulated failure")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    def test_closed_state_on_init(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED

    def test_successful_call_stays_closed(self):
        cb = CircuitBreaker(failure_threshold=3)
        result = cb.call(SucceedingTool(), {})
        assert isinstance(result, Ok)
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(failure_threshold=3)
        tool = FailingTool()
        for _ in range(3):
            cb.call(tool, {})
        assert cb.state == CircuitState.OPEN

    def test_open_circuit_returns_circuit_open_error(self):
        cb = CircuitBreaker(failure_threshold=2)
        tool = FailingTool()
        cb.call(tool, {})
        cb.call(tool, {})
        # Circuit now open
        result = cb.call(SucceedingTool(), {})
        assert isinstance(result, Err)
        assert isinstance(result.error, CircuitOpenError)

    def test_manual_reset_closes_circuit(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.call(FailingTool(), {})
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED

    def test_successful_call_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        tool_fail = FailingTool()
        tool_ok = SucceedingTool()
        cb.call(tool_fail, {})
        cb.call(tool_fail, {})
        cb.call(tool_ok, {})  # success resets counter
        # Failure count is now 0; need 3 more to open
        assert cb.state == CircuitState.CLOSED

    def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)
        cb.call(FailingTool(), {})
        assert cb.state == CircuitState.OPEN
        time.sleep(0.06)
        # Accessing state should transition to HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN
