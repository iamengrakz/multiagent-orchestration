"""
tests/unit/test_saga.py
Book reference: Chapter 13
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

import pytest

from multiagent_orchestration.contracts import MCPToolContract, ToolSchema
from multiagent_orchestration.result import Ok, Err
from multiagent_orchestration.saga import SagaOrchestrator, SagaResult, SagaStep


# ---------------------------------------------------------------------------
# Test tools
# ---------------------------------------------------------------------------

class _TrackingTool(MCPToolContract):
    """Base for tools that track how many times execute() was called."""
    version = "1.0.0"
    description = "tracking"
    input_schema = ToolSchema(required=[], properties={"order_id": {"type": "string"}})
    output_schema = ToolSchema(required=["done"], properties={"done": {"type": "boolean"}})

    def __init__(self):
        self.call_count = 0

    def execute(self, inputs):
        self.call_count += 1
        return {"done": True}


class ReserveInventoryTool(_TrackingTool):
    name = "reserve_inventory"


class ReleaseInventoryTool(_TrackingTool):
    name = "release_inventory"
    description = "compensator for reserve_inventory"


class ChargeCreditCardTool(_TrackingTool):
    name = "charge_credit_card"


class RefundCreditCardTool(_TrackingTool):
    name = "refund_credit_card"
    description = "compensator for charge_credit_card"


class FailingTool(_TrackingTool):
    name = "always_fails"
    def execute(self, inputs):
        raise RuntimeError("simulated downstream failure")


class SendEmailTool(_TrackingTool):
    name = "send_email"
    # No compensator — can't unsend an email


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSagaOrchestrator:

    def _make_saga(self):
        return SagaOrchestrator()

    # ── Happy path ─────────────────────────────────────────────────────────

    def test_all_steps_succeed_returns_succeeded_true(self):
        saga = self._make_saga()
        saga.add_step(SagaStep(tool=ReserveInventoryTool(), compensator=ReleaseInventoryTool()))
        saga.add_step(SagaStep(tool=ChargeCreditCardTool(), compensator=RefundCreditCardTool()))

        result = saga.run(initial_inputs={"order_id": "ORD-001"})

        assert result.succeeded
        assert result.failed_at_step is None
        assert "reserve_inventory" in result.forward_outputs
        assert "charge_credit_card" in result.forward_outputs
        assert all(isinstance(r, Ok) for r in result.forward_outputs.values())

    def test_single_step_saga_succeeds(self):
        saga = self._make_saga()
        saga.add_step(SagaStep(tool=ReserveInventoryTool()))
        result = saga.run(initial_inputs={"order_id": "ORD-002"})
        assert result.succeeded

    # ── Rollback path ──────────────────────────────────────────────────────

    def test_failure_triggers_rollback_of_completed_steps(self):
        reserve = ReserveInventoryTool()
        release = ReleaseInventoryTool()
        saga = self._make_saga()
        saga.add_step(SagaStep(tool=reserve, compensator=release))
        saga.add_step(SagaStep(tool=FailingTool()))

        result = saga.run(initial_inputs={"order_id": "ORD-003"})

        assert result.failed
        assert result.failed_at_step == "always_fails"
        # reserve_inventory completed, so release_inventory should have been called
        assert release.call_count == 1

    def test_rollback_is_lifo_order(self):
        """Compensators are called in reverse order of completion."""
        call_order = []

        class Step1(MCPToolContract):
            name = "step1"; version = "1.0.0"; description = "s1"
            input_schema = ToolSchema(required=[], properties={})
            output_schema = ToolSchema(required=["v"], properties={"v": {"type": "boolean"}})
            def execute(self, inputs): return {"v": True}

        class Comp1(MCPToolContract):
            name = "comp1"; version = "1.0.0"; description = "c1"
            input_schema = ToolSchema(required=[], properties={})
            output_schema = ToolSchema(required=["v"], properties={"v": {"type": "boolean"}})
            def execute(self, inputs): call_order.append("comp1"); return {"v": True}

        class Step2(MCPToolContract):
            name = "step2"; version = "1.0.0"; description = "s2"
            input_schema = ToolSchema(required=[], properties={})
            output_schema = ToolSchema(required=["v"], properties={"v": {"type": "boolean"}})
            def execute(self, inputs): return {"v": True}

        class Comp2(MCPToolContract):
            name = "comp2"; version = "1.0.0"; description = "c2"
            input_schema = ToolSchema(required=[], properties={})
            output_schema = ToolSchema(required=["v"], properties={"v": {"type": "boolean"}})
            def execute(self, inputs): call_order.append("comp2"); return {"v": True}

        class Step3Fail(MCPToolContract):
            name = "step3"; version = "1.0.0"; description = "s3"
            input_schema = ToolSchema(required=[], properties={})
            output_schema = ToolSchema(required=[], properties={})
            def execute(self, inputs): raise RuntimeError("fail")

        saga = self._make_saga()
        saga.add_step(SagaStep(tool=Step1(), compensator=Comp1()))
        saga.add_step(SagaStep(tool=Step2(), compensator=Comp2()))
        saga.add_step(SagaStep(tool=Step3Fail()))

        saga.run(initial_inputs={})

        # LIFO: comp2 should run before comp1
        assert call_order == ["comp2", "comp1"]

    def test_step_without_compensator_recorded_in_uncompensated(self):
        email = SendEmailTool()
        saga = self._make_saga()
        saga.add_step(SagaStep(tool=email, compensator=None))
        saga.add_step(SagaStep(tool=FailingTool()))

        result = saga.run(initial_inputs={"order_id": "ORD-004"})

        assert result.failed
        assert "send_email" in result.uncompensated_steps

    def test_compensation_failure_does_not_halt_remaining_compensations(self):
        """Even if one compensator fails, the others still run."""

        class FailingCompensator(MCPToolContract):
            name = "failing_comp"; version = "1.0.0"; description = "fails"
            input_schema = ToolSchema(required=[], properties={})
            output_schema = ToolSchema(required=[], properties={})
            def execute(self, inputs): raise RuntimeError("comp failed")

        good_comp = ReleaseInventoryTool()

        class Step1(MCPToolContract):
            name = "step_a"; version = "1.0.0"; description = "a"
            input_schema = ToolSchema(required=[], properties={})
            output_schema = ToolSchema(required=["v"], properties={"v": {"type": "boolean"}})
            def execute(self, inputs): return {"v": True}

        class Step2(MCPToolContract):
            name = "step_b"; version = "1.0.0"; description = "b"
            input_schema = ToolSchema(required=[], properties={})
            output_schema = ToolSchema(required=["v"], properties={"v": {"type": "boolean"}})
            def execute(self, inputs): return {"v": True}

        saga = self._make_saga()
        # step_a has a compensator that will fail
        saga.add_step(SagaStep(tool=Step1(), compensator=FailingCompensator()))
        # step_b has a compensator that will succeed
        saga.add_step(SagaStep(tool=Step2(), compensator=good_comp))
        saga.add_step(SagaStep(tool=FailingTool()))

        result = saga.run(initial_inputs={})

        assert result.failed
        # Both compensators were attempted (LIFO: step_b first, then step_a)
        assert "step_b" in result.compensation_outcomes
        assert "step_a" in result.compensation_outcomes
        # step_b's compensator (good_comp) succeeded
        assert isinstance(result.compensation_outcomes["step_b"], Ok)
        # step_a's compensator failed
        assert isinstance(result.compensation_outcomes["step_a"], Err)
        # good_comp was still called even though step_a's comp failed
        assert good_comp.call_count == 1

    # ── SagaResult properties ──────────────────────────────────────────────

    def test_fully_compensated_true_when_all_compensations_succeed(self):
        reserve = ReserveInventoryTool()
        release = ReleaseInventoryTool()
        saga = self._make_saga()
        saga.add_step(SagaStep(tool=reserve, compensator=release))
        saga.add_step(SagaStep(tool=FailingTool()))

        result = saga.run(initial_inputs={"order_id": "ORD-005"})

        assert result.failed
        assert result.fully_compensated

    def test_chaining_add_step_returns_self(self):
        saga = self._make_saga()
        returned = saga.add_step(SagaStep(tool=ReserveInventoryTool()))
        assert returned is saga
