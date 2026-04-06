"""
tests/unit/test_contracts.py
Book reference: Chapter 3
"""

from __future__ import annotations

import pytest
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

from multiagent_orchestration.contracts import MCPToolContract, ToolSchema, ValidationError
from multiagent_orchestration.result import Ok, Err


# ---------------------------------------------------------------------------
# Minimal concrete tool for testing
# ---------------------------------------------------------------------------

class EchoTool(MCPToolContract):
    name = "echo"
    version = "1.0.0"
    description = "Echoes the input message."
    input_schema = ToolSchema(
        required=["message"],
        properties={"message": {"type": "string"}},
    )
    output_schema = ToolSchema(
        required=["echo"],
        properties={"echo": {"type": "string"}},
    )

    def execute(self, inputs):
        return {"echo": inputs["message"]}


class BrokenOutputTool(MCPToolContract):
    """Tool that returns an output violating its own schema."""
    name = "broken"
    version = "1.0.0"
    description = "Returns invalid output."
    input_schema = ToolSchema(
        required=["x"],
        properties={"x": {"type": "integer"}},
    )
    output_schema = ToolSchema(
        required=["result"],
        properties={"result": {"type": "string"}},
    )

    def execute(self, inputs):
        return {"result": 999}  # integer, violates "type": "string"


class RaisingTool(MCPToolContract):
    """Tool whose execute() raises unconditionally."""
    name = "raising"
    version = "1.0.0"
    description = "Always raises."
    input_schema = ToolSchema(required=[], properties={})
    output_schema = ToolSchema(required=[], properties={})

    def execute(self, inputs):
        raise RuntimeError("deliberate failure")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestToolSchema:
    def test_valid_input_passes(self):
        schema = ToolSchema(
            required=["name"],
            properties={"name": {"type": "string"}},
        )
        schema.validate({"name": "Alice"})  # should not raise

    def test_missing_required_raises(self):
        schema = ToolSchema(
            required=["name"],
            properties={"name": {"type": "string"}},
        )
        with pytest.raises(ValidationError):
            schema.validate({})

    def test_wrong_type_raises(self):
        schema = ToolSchema(
            required=["count"],
            properties={"count": {"type": "integer"}},
        )
        with pytest.raises(ValidationError):
            schema.validate({"count": "not-an-int"})

    def test_additional_properties_rejected_by_default(self):
        schema = ToolSchema(
            required=["x"],
            properties={"x": {"type": "integer"}},
            additional_properties=False,
        )
        with pytest.raises(ValidationError):
            schema.validate({"x": 1, "unexpected": "value"})

    def test_additional_properties_allowed_when_flag_set(self):
        schema = ToolSchema(
            required=["x"],
            properties={"x": {"type": "integer"}},
            additional_properties=True,
        )
        schema.validate({"x": 1, "extra": "ok"})  # should not raise


class TestMCPToolContractCall:
    def test_successful_call_returns_ok(self):
        result = EchoTool().call({"message": "hello"})
        assert isinstance(result, Ok)
        assert result.value == {"echo": "hello"}

    def test_invalid_input_returns_err(self):
        result = EchoTool().call({"wrong_key": "hello"})
        assert isinstance(result, Err)
        assert isinstance(result.error, ValidationError)

    def test_invalid_output_returns_err(self):
        result = BrokenOutputTool().call({"x": 42})
        assert isinstance(result, Err)
        assert isinstance(result.error, ValidationError)

    def test_execute_exception_returns_err(self):
        result = RaisingTool().call({})
        assert isinstance(result, Err)
        assert "deliberate failure" in str(result.error)

    def test_fingerprint_is_stable(self):
        tool = EchoTool()
        fp1 = tool.fingerprint({"message": "hi"})
        fp2 = tool.fingerprint({"message": "hi"})
        assert fp1 == fp2

    def test_fingerprint_differs_on_different_inputs(self):
        tool = EchoTool()
        assert tool.fingerprint({"message": "hi"}) != tool.fingerprint({"message": "bye"})

    def test_fingerprint_normalises_key_order(self):
        tool = EchoTool()
        fp1 = tool.fingerprint({"a": 1, "b": 2})
        fp2 = tool.fingerprint({"b": 2, "a": 1})
        assert fp1 == fp2
