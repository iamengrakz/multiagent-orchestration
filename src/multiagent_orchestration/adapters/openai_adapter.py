"""
adapters/openai_adapter.py — OpenAIAdapter
===========================================
Book reference: Chapter 7, §7.7 — "Wiring to OpenAI"

Requires: ``pip install "multiagent-orchestration[openai]"``

Supports both OpenAI and Azure OpenAI endpoints via the ``openai`` SDK's
unified client interface.

Environment variables:
    OPENAI_API_KEY        — required for openai.com
    OPENAI_API_BASE       — optional; set for Azure deployments
    OPENAI_API_VERSION    — optional; required for Azure

Usage (Chapter 7, Listing 7.4)::

    import os
    from multiagent_orchestration.adapters.openai_adapter import OpenAIAdapter

    adapter = OpenAIAdapter(model="gpt-4o", api_key=os.environ["OPENAI_API_KEY"])
"""

from __future__ import annotations

from multiagent_orchestration.adapters.base import (
    CompletionRequest,
    CompletionResponse,
    LLMAdapter,
)


class OpenAIAdapter(LLMAdapter):
    """OpenAI / Azure OpenAI adapter.

    Args:
        model: Model identifier, e.g. ``"gpt-4o"`` or ``"gpt-4-turbo"``.
        api_key: OpenAI API key.  Falls back to ``OPENAI_API_KEY`` env var
            if ``None``.
        base_url: Optional alternative base URL (Azure, local proxies).
        timeout: Request timeout in seconds.  Defaults to ``60``.
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        try:
            import openai
        except ImportError as exc:
            raise ImportError(
                "OpenAIAdapter requires openai. "
                "Install it with: pip install 'multiagent-orchestration[openai]'"
            ) from exc

        self._model = model
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
        )

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        response = self._client.chat.completions.create(
            model=self._model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            messages=[
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_message},
            ],
        )
        choice = response.choices[0]
        return CompletionResponse(
            content=choice.message.content or "",
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            model=self._model,
            raw=response,
        )

    @property
    def model_name(self) -> str:
        return self._model
