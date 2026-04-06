"""
adapters/stub_adapter.py — StubLLMAdapter
==========================================
Book reference: Chapter 7, §7.6 — "Testing Without API Keys"

A deterministic, zero-dependency adapter used by all examples and unit tests.
Returns configurable canned responses; never makes a network call.

Usage::

    adapter = StubLLMAdapter(
        response_map={
            "summarise": "This paper discusses transformer architectures.",
        },
        default_response="[stub] No response configured for this prompt.",
    )
"""

from __future__ import annotations

from multiagent_orchestration.adapters.base import (
    CompletionRequest,
    CompletionResponse,
    LLMAdapter,
)


class StubLLMAdapter(LLMAdapter):
    """Deterministic stub adapter for examples and testing.

    Args:
        response_map: Mapping of keyword → response string.  If any key
            appears in the user message (case-insensitive), that response
            is returned.
        default_response: Fallback when no keyword matches.
    """

    def __init__(
        self,
        response_map: dict[str, str] | None = None,
        default_response: str = "[stub] Acknowledged.",
    ) -> None:
        self._response_map = {k.lower(): v for k, v in (response_map or {}).items()}
        self._default = default_response

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        msg_lower = request.user_message.lower()
        content = self._default
        for keyword, response in self._response_map.items():
            if keyword in msg_lower:
                content = response
                break
        return CompletionResponse(
            content=content,
            input_tokens=len(request.user_message.split()),
            output_tokens=len(content.split()),
            model=self.model_name,
        )

    @property
    def model_name(self) -> str:
        return "stub-v1"
