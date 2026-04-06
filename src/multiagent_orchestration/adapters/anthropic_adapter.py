"""
adapters/anthropic_adapter.py — AnthropicAdapter
==================================================
Book reference: Chapter 7, §7.8 — "Wiring to Anthropic Claude"

Requires: ``pip install "multiagent-orchestration[anthropic]"``

Environment variables:
    ANTHROPIC_API_KEY     — required

Usage (Chapter 7, Listing 7.5)::

    import os
    from multiagent_orchestration.adapters.anthropic_adapter import AnthropicAdapter

    adapter = AnthropicAdapter(
        model="claude-sonnet-4-20250514",
        api_key=os.environ["ANTHROPIC_API_KEY"],
    )
"""

from __future__ import annotations

from multiagent_orchestration.adapters.base import (
    CompletionRequest,
    CompletionResponse,
    LLMAdapter,
)


class AnthropicAdapter(LLMAdapter):
    """Anthropic Claude adapter.

    Args:
        model: Model string, e.g. ``"claude-sonnet-4-20250514"``.
        api_key: Anthropic API key.  Falls back to ``ANTHROPIC_API_KEY``
            env var if ``None``.
        timeout: Request timeout in seconds.  Defaults to ``60``.
    """

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "AnthropicAdapter requires anthropic. "
                "Install it with: pip install 'multiagent-orchestration[anthropic]'"
            ) from exc

        self._model = model
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout)

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=request.max_tokens,
            system=request.system_prompt,
            messages=[{"role": "user", "content": request.user_message}],
        )
        content = response.content[0].text if response.content else ""
        return CompletionResponse(
            content=content,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=self._model,
            raw=response,
        )

    @property
    def model_name(self) -> str:
        return self._model
