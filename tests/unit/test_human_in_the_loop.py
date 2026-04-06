"""
tests/unit/test_human_in_the_loop.py
Book reference: Chapter 11 (Advanced)
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

import pytest

from multiagent_orchestration.contracts import MCPToolContract, ToolSchema
from multiagent_orchestration.human_in_the_loop import (
    CustomRule,
    EscalationDecision,
    EscalationPolicy,
    EscalationTier,
    HighCostRule,
    HumanInTheLoop,
    PipelineAbortedByHuman,
    SensitiveActionRule,
    StubHumanGateway,
)


def make_tool(name: str, side_effecting: bool = False) -> MCPToolContract:
    class T(MCPToolContract):
        input_schema = ToolSchema(required=[], properties={"data": {"type": "string"}})
        output_schema = ToolSchema(required=[], properties={})
        def execute(self, inputs): return {}
    T.name = name
    T.version = "1.0.0"
    T.description = name
    T.side_effecting = side_effecting
    return T()


class TestEscalationPolicy:

    def test_no_rules_returns_auto(self):
        policy = EscalationPolicy(rules=[])
        tier, reason = policy.decide(make_tool("t"), {})
        assert tier == EscalationTier.AUTO

    def test_sensitive_action_rule_triggers_review(self):
        policy = EscalationPolicy(rules=[
            SensitiveActionRule(sensitive_tools={"email_dispatch"})
        ])
        tier, _ = policy.decide(make_tool("email_dispatch"), {})
        assert tier == EscalationTier.REVIEW

    def test_sensitive_action_rule_does_not_trigger_for_other_tools(self):
        policy = EscalationPolicy(rules=[
            SensitiveActionRule(sensitive_tools={"email_dispatch"})
        ])
        tier, _ = policy.decide(make_tool("web_search"), {})
        assert tier == EscalationTier.AUTO

    def test_highest_tier_wins_when_multiple_rules_match(self):
        policy = EscalationPolicy(rules=[
            SensitiveActionRule(sensitive_tools={"pay"}, tier=EscalationTier.REVIEW),
            CustomRule(
                fn=lambda tool, inputs: EscalationTier.ABORT if tool.name == "pay" else None,
                reason_text="payment tools always abort",
            ),
        ])
        tier, _ = policy.decide(make_tool("pay"), {})
        assert tier == EscalationTier.ABORT

    def test_custom_rule_used_as_lambda(self):
        policy = EscalationPolicy(rules=[
            CustomRule(
                fn=lambda tool, inputs: EscalationTier.OVERRIDE
                    if inputs.get("amount", 0) > 10_000 else None,
                reason_text="large transaction requires override",
            )
        ])
        tier, _ = policy.decide(make_tool("payment"), {"amount": 50_000})
        assert tier == EscalationTier.OVERRIDE

    def test_custom_rule_returns_none_for_small_amount(self):
        policy = EscalationPolicy(rules=[
            CustomRule(
                fn=lambda tool, inputs: EscalationTier.OVERRIDE
                    if inputs.get("amount", 0) > 10_000 else None,
                reason_text="n/a",
            )
        ])
        tier, _ = policy.decide(make_tool("payment"), {"amount": 100})
        assert tier == EscalationTier.AUTO


class TestHumanInTheLoop:

    def _make_hitl(self, rules=None, auto_approve=True):
        return HumanInTheLoop(
            policy=EscalationPolicy(rules=rules or []),
            gateway=StubHumanGateway(auto_approve=auto_approve),
        )

    def test_auto_tier_returns_without_calling_gateway(self):
        hitl = self._make_hitl()
        decision = hitl.check(make_tool("safe_tool"), {})
        assert decision.tier == EscalationTier.AUTO

    def test_sensitive_tool_review_approved_returns_auto(self):
        hitl = HumanInTheLoop(
            policy=EscalationPolicy(rules=[
                SensitiveActionRule(sensitive_tools={"email"})
            ]),
            gateway=StubHumanGateway(auto_approve=True),
        )
        decision = hitl.check(make_tool("email"), {})
        assert decision.tier == EscalationTier.AUTO

    def test_abort_decision_raises_pipeline_aborted(self):
        hitl = HumanInTheLoop(
            policy=EscalationPolicy(rules=[
                SensitiveActionRule(
                    sensitive_tools={"dangerous"},
                    tier=EscalationTier.REVIEW,
                )
            ]),
            gateway=StubHumanGateway(auto_approve=False),
        )
        with pytest.raises(PipelineAbortedByHuman):
            hitl.check(make_tool("dangerous"), {})

    def test_override_returns_corrected_inputs(self):
        corrected = {"query": "sanitised query"}
        hitl = HumanInTheLoop(
            policy=EscalationPolicy(rules=[
                CustomRule(
                    fn=lambda t, i: EscalationTier.OVERRIDE,
                    reason_text="always override for test",
                )
            ]),
            gateway=StubHumanGateway(
                auto_approve=True,
                corrected_inputs_map={"my_tool": corrected},
            ),
        )
        decision = hitl.check(make_tool("my_tool"), {"query": "raw input"})
        assert decision.tier == EscalationTier.OVERRIDE
        assert decision.corrected_inputs == corrected
