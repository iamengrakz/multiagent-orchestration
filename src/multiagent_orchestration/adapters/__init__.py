"""
adapters/__init__.py
"""

from multiagent_orchestration.adapters.base import LLMAdapter, CompletionRequest, CompletionResponse
from multiagent_orchestration.adapters.stub_adapter import StubLLMAdapter

__all__ = [
    "LLMAdapter",
    "CompletionRequest",
    "CompletionResponse",
    "StubLLMAdapter",
]
