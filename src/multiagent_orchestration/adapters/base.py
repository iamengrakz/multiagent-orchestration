"""
adapters/base.py — LLMAdapter abstract base
===========================================
Book reference: Chapter 7, §7.5 — "The Pluggable Adapter Pattern"

Decouples the orchestration layer from any specific LLM provider.
Concrete implementations live alongside this file:

- ``stub_adapter.py``      — deterministic, zero-dep stub for examples/tests
- ``openai_adapter.py``    — OpenAI / Azure OpenAI
- ``anthropic_adapter.py`` — Anthropic Claude
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any


@dataclass
class CompletionRequest:
    """Normalised LLM request envelope."""

    system_prompt: str
    user_message: str
    max_tokens: int = 1024
    temperature: float = 0.0
    metadata: dict[str, Any] | None = None


@dataclass
class CompletionResponse:
    """Normalised LLM response envelope."""

    content: str
    input_tokens: int
    output_tokens: int
    model: str
    raw: Any = None  # provider-specific response object


class LLMAdapter(abc.ABC):
    """Abstract base class for all LLM provider adapters.

    Book reference: Chapter 7, §7.5

    Subclasses must implement :meth:`complete`.
    """

    @abc.abstractmethod
    def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Send *request* to the LLM and return a normalised response."""

    @property
    @abc.abstractmethod
    def model_name(self) -> str:
        """Human-readable model identifier (e.g. ``"gpt-4o"``)."""
