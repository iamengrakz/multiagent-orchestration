"""
human_in_the_loop.py — Escalation Ladder
==========================================
Book reference: Chapter 11 (Advanced) — "Human-in-the-Loop Escalation"

The editor's report listed this as a key differentiator:

    "Human-in-the-loop escalation ladder example."

Production multi-agent systems must know when to stop and ask a human.
This module implements a three-tier escalation ladder:

    Tier 0 — AUTO:      the orchestrator proceeds without interruption.
    Tier 1 — REVIEW:    a human must approve before execution continues.
    Tier 2 — OVERRIDE:  a human must supply corrected inputs; the agent's
                        own inputs are discarded.
    Tier 3 — ABORT:     execution is halted and a human must restart the run.

The :class:`EscalationPolicy` decides which tier applies based on pluggable
:class:`EscalationRule` callables.  The :class:`HumanGateway` handles the
actual handoff — in production this sends a Slack/email/webhook notification
and blocks until a response arrives; the default ``StubHumanGateway``
auto-approves for testing.

Usage (Chapter 11, Listing 11.4)::

    policy = EscalationPolicy(rules=[
        HighCostRule(token_threshold=5_000),
        SensitiveActionRule(sensitive_tools={"email_dispatch", "payment_tool"}),
    ])

    gateway = StubHumanGateway(auto_approve=True)
    hitl = HumanInTheLoop(policy=policy, gateway=gateway)

    decision = hitl.check(tool=email_tool, inputs=inputs)
    if decision.tier == EscalationTier.ABORT:
        raise PipelineAbortedByHuman(decision.reason)
    if decision.tier == EscalationTier.OVERRIDE:
        inputs = decision.corrected_inputs
"""

from __future__ import annotations

import abc
import enum
from dataclasses import dataclass, field
from typing import Any, Callable

from multiagent_orchestration.contracts import MCPToolContract


# ---------------------------------------------------------------------------
# Escalation tiers
# ---------------------------------------------------------------------------

class EscalationTier(enum.Enum):
    """The four tiers of the escalation ladder.

    Book reference: Chapter 11, §11.2 — "The Four-Tier Model"
    """
    AUTO = "auto"          # proceed without interruption
    REVIEW = "review"      # human must approve; inputs unchanged
    OVERRIDE = "override"  # human supplies corrected inputs
    ABORT = "abort"        # halt the pipeline entirely


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

@dataclass
class EscalationDecision:
    """Outcome of an escalation check.

    Attributes:
        tier: The escalation level decided by the policy.
        reason: Human-readable explanation of why this tier was chosen.
        corrected_inputs: Populated only when ``tier == OVERRIDE``; contains
            the human-supplied replacement inputs.
    """
    tier: EscalationTier
    reason: str
    corrected_inputs: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

class EscalationRule(abc.ABC):
    """Abstract base for a single escalation rule.

    Book reference: Chapter 11, §11.3 — "Composable Escalation Rules"

    Implement :meth:`evaluate` to return the appropriate tier for a given
    ``(tool, inputs)`` pair, or ``None`` if this rule does not apply.
    """

    @abc.abstractmethod
    def evaluate(
        self,
        tool: MCPToolContract,
        inputs: dict[str, Any],
    ) -> EscalationTier | None:
        """Return the escalation tier, or ``None`` if the rule does not apply."""

    @property
    @abc.abstractmethod
    def reason(self) -> str:
        """Short description shown in logs and notifications."""


class HighCostRule(EscalationRule):
    """Escalate to REVIEW when estimated token cost exceeds a threshold.

    Book reference: Chapter 11, §11.4 — "Cost-Based Escalation"

    Args:
        token_threshold: Estimated tokens above which REVIEW is triggered.
            Estimate is ``len(json.dumps(inputs)) // 4`` (rough token proxy).
        tier: Escalation tier to apply (default: ``REVIEW``).
    """

    def __init__(
        self,
        token_threshold: int = 5_000,
        tier: EscalationTier = EscalationTier.REVIEW,
    ) -> None:
        self._threshold = token_threshold
        self._tier = tier

    def evaluate(self, tool: MCPToolContract, inputs: dict[str, Any]) -> EscalationTier | None:
        import json
        estimated = len(json.dumps(inputs)) // 4
        if estimated > self._threshold:
            return self._tier
        return None

    @property
    def reason(self) -> str:
        return f"Estimated token cost exceeds {self._threshold:,}"


class SensitiveActionRule(EscalationRule):
    """Escalate to REVIEW when a side-effecting tool is in the sensitive set.

    Book reference: Chapter 11, §11.5 — "Sensitive-Action Gating"

    Args:
        sensitive_tools: Set of tool names requiring human review before
            execution.
        tier: Escalation tier to apply (default: ``REVIEW``).
    """

    def __init__(
        self,
        sensitive_tools: set[str],
        tier: EscalationTier = EscalationTier.REVIEW,
    ) -> None:
        self._sensitive = sensitive_tools
        self._tier = tier

    def evaluate(self, tool: MCPToolContract, inputs: dict[str, Any]) -> EscalationTier | None:
        if tool.name in self._sensitive:
            return self._tier
        return None

    @property
    def reason(self) -> str:
        return f"Tool is in sensitive set: {sorted(self._sensitive)}"


class CustomRule(EscalationRule):
    """Wrap any callable as an escalation rule.

    Args:
        fn: ``(tool, inputs) -> EscalationTier | None``
        reason_text: Description for logs.
    """

    def __init__(
        self,
        fn: Callable[[MCPToolContract, dict[str, Any]], EscalationTier | None],
        reason_text: str,
    ) -> None:
        self._fn = fn
        self._reason_text = reason_text

    def evaluate(self, tool: MCPToolContract, inputs: dict[str, Any]) -> EscalationTier | None:
        return self._fn(tool, inputs)

    @property
    def reason(self) -> str:
        return self._reason_text


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

class EscalationPolicy:
    """Evaluates a list of rules and returns the highest-priority tier.

    Book reference: Chapter 11, §11.3 — "Policy as a Rule Chain"

    Rules are evaluated in order.  The highest tier found across all
    matching rules wins (ABORT > OVERRIDE > REVIEW > AUTO).

    Args:
        rules: Ordered list of :class:`EscalationRule` instances.
    """

    _TIER_PRIORITY = {
        EscalationTier.AUTO: 0,
        EscalationTier.REVIEW: 1,
        EscalationTier.OVERRIDE: 2,
        EscalationTier.ABORT: 3,
    }

    def __init__(self, rules: list[EscalationRule] | None = None) -> None:
        self._rules = rules or []

    def decide(
        self,
        tool: MCPToolContract,
        inputs: dict[str, Any],
    ) -> tuple[EscalationTier, str]:
        """Return ``(tier, reason)`` for the given tool invocation."""
        best_tier = EscalationTier.AUTO
        best_reason = "All rules passed — proceeding automatically."

        for rule in self._rules:
            tier = rule.evaluate(tool, inputs)
            if tier is not None:
                if self._TIER_PRIORITY[tier] > self._TIER_PRIORITY[best_tier]:
                    best_tier = tier
                    best_reason = rule.reason

        return best_tier, best_reason


# ---------------------------------------------------------------------------
# Human Gateway
# ---------------------------------------------------------------------------

class HumanGateway(abc.ABC):
    """Handles the actual human handoff.

    Book reference: Chapter 11, §11.6 — "Gateway Implementations"
    """

    @abc.abstractmethod
    def request_approval(
        self,
        tool: MCPToolContract,
        inputs: dict[str, Any],
        tier: EscalationTier,
        reason: str,
    ) -> EscalationDecision:
        """Block until a human responds and return their decision."""


class StubHumanGateway(HumanGateway):
    """Deterministic stub for testing and examples.

    Args:
        auto_approve: When ``True`` (default), always approves at REVIEW/OVERRIDE.
            When ``False``, always ABORTs — useful for testing abort paths.
        corrected_inputs_map: Optional mapping of tool name → corrected inputs
            returned for OVERRIDE tier.
    """

    def __init__(
        self,
        auto_approve: bool = True,
        corrected_inputs_map: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._approve = auto_approve
        self._corrected = corrected_inputs_map or {}

    def request_approval(
        self,
        tool: MCPToolContract,
        inputs: dict[str, Any],
        tier: EscalationTier,
        reason: str,
    ) -> EscalationDecision:
        if not self._approve:
            return EscalationDecision(
                tier=EscalationTier.ABORT,
                reason=f"[stub] Human rejected: {reason}",
            )
        if tier == EscalationTier.OVERRIDE:
            corrected = self._corrected.get(tool.name, inputs)
            return EscalationDecision(
                tier=EscalationTier.OVERRIDE,
                reason=f"[stub] Human supplied corrected inputs for '{tool.name}'",
                corrected_inputs=corrected,
            )
        return EscalationDecision(
            tier=EscalationTier.AUTO,
            reason=f"[stub] Human approved '{tool.name}' at tier {tier.value}",
        )


# ---------------------------------------------------------------------------
# Main interface
# ---------------------------------------------------------------------------

class PipelineAbortedByHuman(Exception):
    """Raised when escalation results in an ABORT decision."""


class HumanInTheLoop:
    """Checks escalation policy and routes to the gateway when needed.

    Book reference: Chapter 11, §11.7 — "Wiring HumanInTheLoop into the Orchestrator"

    Args:
        policy: :class:`EscalationPolicy` with configured rules.
        gateway: :class:`HumanGateway` implementation.
    """

    def __init__(self, policy: EscalationPolicy, gateway: HumanGateway) -> None:
        self._policy = policy
        self._gateway = gateway

    def check(
        self,
        tool: MCPToolContract,
        inputs: dict[str, Any],
    ) -> EscalationDecision:
        """Evaluate the policy and return a decision.

        If the policy returns AUTO, returns immediately without calling
        the gateway (zero latency on the happy path).

        Args:
            tool: The tool about to be invoked.
            inputs: The inputs to be passed to the tool.

        Returns:
            An :class:`EscalationDecision` — caller must inspect ``.tier``.

        Raises:
            PipelineAbortedByHuman: If the gateway returns ABORT.
        """
        tier, reason = self._policy.decide(tool, inputs)

        if tier == EscalationTier.AUTO:
            return EscalationDecision(tier=EscalationTier.AUTO, reason=reason)

        decision = self._gateway.request_approval(tool, inputs, tier, reason)

        if decision.tier == EscalationTier.ABORT:
            raise PipelineAbortedByHuman(
                f"Pipeline aborted by human for tool '{tool.name}': {decision.reason}"
            )

        return decision
