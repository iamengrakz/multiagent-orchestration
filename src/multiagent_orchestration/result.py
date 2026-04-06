"""
result.py — Ok / Err discriminated union
========================================
Book reference: Chapter 2, §2.5 — "Typed Results Over Exceptions"

A lightweight ``Result`` type that makes the success / failure distinction
explicit in the type system.  Every tool invocation, every DAG step, and
every middleware layer returns a ``Result``; callers must inspect it before
proceeding.

This avoids the "exception-as-control-flow" antipattern that makes multi-agent
pipelines difficult to reason about and test.

Usage::

    result = tool.call({"query": "LLM orchestration"})

    match result:
        case Ok(value):
            process(value)
        case Err(exc):
            log.error("tool failed", exc_info=exc)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")
E = TypeVar("E", bound=Exception)


@dataclass(frozen=True)
class Ok(Generic[T]):
    """Represents a successful computation.

    Attributes:
        value: The successful return value.
    """

    value: T

    def is_ok(self) -> bool:
        return True

    def is_err(self) -> bool:
        return False

    def unwrap(self) -> T:
        """Return the inner value.

        Raises:
            Never — ``unwrap()`` on ``Ok`` is always safe.
        """
        return self.value

    def unwrap_or(self, default: T) -> T:  # noqa: ARG002
        return self.value

    def __repr__(self) -> str:  # pragma: no cover
        return f"Ok({self.value!r})"


@dataclass(frozen=True)
class Err(Generic[E]):
    """Represents a failed computation.

    Attributes:
        error: The exception that caused the failure.
    """

    error: E

    def is_ok(self) -> bool:
        return False

    def is_err(self) -> bool:
        return True

    def unwrap(self) -> None:
        """Raise the inner error.

        Raises:
            E: Always.
        """
        raise self.error

    def unwrap_or(self, default: object) -> object:
        return default

    def __repr__(self) -> str:  # pragma: no cover
        return f"Err({self.error!r})"


# Type alias used in annotations throughout the codebase.
Result = Ok[T] | Err[E]
