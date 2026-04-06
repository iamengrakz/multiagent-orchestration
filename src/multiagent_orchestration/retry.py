"""
retry.py — exponential_backoff and RetryPolicy
===============================================
Book reference: Chapter 8, §8.6 — "Retry Policies and Back-off Strategies"

Provides a simple, composable retry decorator and ``RetryPolicy`` dataclass.
Designed to wrap the ``execute()`` bodies of tools that call external APIs,
not the ``call()`` wrapper (which handles validation).

Usage (Chapter 8, Listing 8.5)::

    class WebSearchTool(MCPToolContract):
        retry_policy = RetryPolicy(max_attempts=3, base_delay=1.0, jitter=True)

        def execute(self, inputs):
            return with_retry(self._fetch, inputs, policy=self.retry_policy)

        def _fetch(self, inputs):
            ...  # actual API call
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

F = TypeVar("F")


@dataclass
class RetryPolicy:
    """Configuration for retry behaviour.

    Book reference: Chapter 8, §8.6

    Attributes:
        max_attempts: Total attempts including the first.  Defaults to ``3``.
        base_delay: Initial delay in seconds.  Doubles each retry.  Defaults
            to ``1.0``.
        max_delay: Cap on the computed delay.  Defaults to ``30.0``.
        jitter: Add uniform random jitter of ±50% of the computed delay.
            Prevents thundering herd.  Defaults to ``True``.
        retriable_exceptions: Tuple of exception types to retry on.  Defaults
            to ``(Exception,)`` (retry on anything).
    """

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    jitter: bool = True
    retriable_exceptions: tuple[type[Exception], ...] = (Exception,)

    def delay_for_attempt(self, attempt: int) -> float:
        """Compute sleep duration for *attempt* (0-indexed).

        Args:
            attempt: Zero-based attempt index.

        Returns:
            Seconds to sleep before the next attempt.
        """
        raw = min(self.base_delay * (2 ** attempt), self.max_delay)
        if self.jitter:
            raw *= 0.5 + random.random() * 0.5  # uniform [0.5, 1.0] × raw
        return raw


def with_retry(
    fn: Callable[..., Any],
    *args: Any,
    policy: RetryPolicy | None = None,
    **kwargs: Any,
) -> Any:
    """Call *fn* with retry logic defined by *policy*.

    Args:
        fn: The callable to retry.
        *args: Positional arguments forwarded to *fn*.
        policy: :class:`RetryPolicy` instance.  Defaults to no-retry
            (single attempt).
        **kwargs: Keyword arguments forwarded to *fn*.

    Returns:
        The return value of *fn* on success.

    Raises:
        The last exception from *fn* if all attempts are exhausted.
    """
    p = policy or RetryPolicy(max_attempts=1)
    last_exc: Exception | None = None

    for attempt in range(p.max_attempts):
        try:
            return fn(*args, **kwargs)
        except p.retriable_exceptions as exc:
            last_exc = exc
            if attempt < p.max_attempts - 1:
                delay = p.delay_for_attempt(attempt)
                time.sleep(delay)

    assert last_exc is not None  # always set after at least one attempt
    raise last_exc
