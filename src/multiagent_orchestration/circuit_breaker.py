"""
circuit_breaker.py — CircuitBreaker
=====================================
Book reference: Chapter 10, §10.1–10.5

Wraps any :class:`~multiagent_orchestration.contracts.MCPToolContract`'s
``execute()`` with the classic three-state circuit breaker pattern:

- **CLOSED** (normal): calls pass through; failures are counted.
- **OPEN** (tripped): calls are immediately rejected without executing the tool;
  after ``recovery_timeout`` seconds the breaker transitions to HALF-OPEN.
- **HALF-OPEN** (probing): one trial call is allowed through; if it succeeds,
  the breaker resets to CLOSED; if it fails, it returns to OPEN.

Book pattern output marker (Chapter 10)::

    ⚡  CIRCUIT OPEN — financial data tool failing; degraded response served ✓

Usage (Chapter 10, Listing 10.2)::

    cb = CircuitBreaker(
        failure_threshold=3,
        recovery_timeout=30.0,
        half_open_max_calls=1,
    )

    result = cb.call(market_data_tool, inputs)
    match result:
        case Ok(data):
            ...
        case Err(CircuitOpenError()):
            serve_cached_data()
"""

from __future__ import annotations

import enum
import threading
import time
from typing import Any

from multiagent_orchestration.contracts import MCPToolContract
from multiagent_orchestration.result import Ok, Err, Result


class CircuitState(enum.Enum):
    """The three states of a circuit breaker.

    Book reference: Chapter 10, §10.2 — "State Machine Overview"
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised (wrapped in Err) when a call is rejected because the circuit is open.

    Book reference: Chapter 10, §10.3 — "Fast-Fail Rejection"
    """

    def __init__(self, tool_name: str, retry_after: float) -> None:
        self.tool_name = tool_name
        self.retry_after = retry_after
        super().__init__(
            f"Circuit OPEN for tool '{tool_name}'. "
            f"Retry after {retry_after:.1f}s."
        )


class CircuitBreaker:
    """Thread-safe circuit breaker for :class:`MCPToolContract` calls.

    Book reference: Chapter 10, §10.4 — "The CircuitBreaker Implementation"

    Args:
        failure_threshold: Number of consecutive failures that trip the breaker
            from CLOSED → OPEN.  Defaults to ``3``.
        recovery_timeout: Seconds to wait in OPEN state before transitioning to
            HALF-OPEN.  Defaults to ``30.0``.
        half_open_max_calls: Number of trial calls permitted in HALF-OPEN state.
            Defaults to ``1``.
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float | None = None
        self._half_open_call_count = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state

    def call(
        self,
        tool: MCPToolContract,
        inputs: dict[str, Any],
    ) -> Result[dict[str, Any], Exception]:
        """Execute *tool* with *inputs* through the circuit breaker.

        Args:
            tool: The tool to execute.
            inputs: Raw inputs forwarded to ``tool.call()``.

        Returns:
            :class:`~multiagent_orchestration.result.Ok` on success, or
            :class:`~multiagent_orchestration.result.Err` containing either a
            :class:`CircuitOpenError` (circuit is open) or the underlying
            tool error (circuit is closed/half-open and the call failed).
        """
        with self._lock:
            self._maybe_transition_to_half_open()

            if self._state == CircuitState.OPEN:
                retry_after = self._retry_after()
                return Err(CircuitOpenError(tool.name, retry_after))

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_call_count >= self._half_open_max_calls:
                    return Err(CircuitOpenError(tool.name, 0.0))
                self._half_open_call_count += 1

        result = tool.call(inputs)

        with self._lock:
            if isinstance(result, Ok):
                self._on_success()
            else:
                self._on_failure()

        return result

    def reset(self) -> None:
        """Manually reset the breaker to CLOSED state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._last_failure_time = None
            self._half_open_call_count = 0

    # ------------------------------------------------------------------
    # Internal state transitions
    # ------------------------------------------------------------------

    def _on_success(self) -> None:
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = None
        self._half_open_call_count = 0

    def _on_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._failure_threshold:
            self._state = CircuitState.OPEN

    def _maybe_transition_to_half_open(self) -> None:
        if (
            self._state == CircuitState.OPEN
            and self._last_failure_time is not None
            and (time.monotonic() - self._last_failure_time) >= self._recovery_timeout
        ):
            self._state = CircuitState.HALF_OPEN
            self._half_open_call_count = 0

    def _retry_after(self) -> float:
        if self._last_failure_time is None:
            return 0.0
        elapsed = time.monotonic() - self._last_failure_time
        return max(0.0, self._recovery_timeout - elapsed)
