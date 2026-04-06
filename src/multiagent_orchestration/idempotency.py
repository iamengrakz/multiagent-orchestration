"""
idempotency.py — IdempotencyMiddleware
=======================================
Book reference: Chapter 8, §8.1–8.5

Prevents duplicate side effects when a tool is retried after a transient
failure.  The pattern mirrors Redis SET-NX (set-if-not-exists): before
executing a side-effecting tool, attempt to atomically claim an idempotency
key.  If the key already exists, the previous result is returned immediately
without re-executing.

Book pattern output marker (Chapter 8)::

    ♻️   IDEMPOTENT RETRY HANDLED — duplicate email prevented ✓

The middleware is **pluggable**: swap ``InMemoryStore`` (default, zero deps)
for ``RedisStore`` (requires ``pip install multiagent-orchestration[redis]``)
by changing one line.

Usage (Chapter 8, Listing 8.3)::

    store = InMemoryStore()                   # or RedisStore(client)
    middleware = IdempotencyMiddleware(store)

    result = middleware.call(tool, inputs, idempotency_key="send-report-2025-04-05")
"""

from __future__ import annotations

import abc
import json
import threading
from typing import Any

from multiagent_orchestration.contracts import MCPToolContract
from multiagent_orchestration.result import Ok, Err, Result


# ---------------------------------------------------------------------------
# Store abstraction
# ---------------------------------------------------------------------------

class IdempotencyStore(abc.ABC):
    """Abstract backing store for idempotency keys.

    Book reference: Chapter 8, §8.3 — "The Pluggable Store Interface"
    """

    @abc.abstractmethod
    def set_if_absent(self, key: str, value: str) -> bool:
        """Atomically store *value* under *key* if *key* does not yet exist.

        Args:
            key: Idempotency key (e.g. ``"send-email-<sha256>"``)
            value: JSON-serialised result to store.

        Returns:
            ``True`` if the key was newly created (tool should execute).
            ``False`` if the key already existed (tool should be skipped).
        """

    @abc.abstractmethod
    def get(self, key: str) -> str | None:
        """Return the stored value for *key*, or ``None`` if absent."""


# ---------------------------------------------------------------------------
# In-memory store (default, zero deps)
# ---------------------------------------------------------------------------

class InMemoryStore(IdempotencyStore):
    """Thread-safe in-memory idempotency store.

    Book reference: Chapter 8, §8.4 — "InMemoryStore for Testing and Dev"

    Uses a ``threading.Lock`` to simulate the atomicity of Redis SET-NX.
    Not suitable for multi-process deployments; use ``RedisStore`` there.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._lock = threading.Lock()

    def set_if_absent(self, key: str, value: str) -> bool:
        with self._lock:
            if key in self._store:
                return False
            self._store[key] = value
            return True

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._store.get(key)

    def clear(self) -> None:
        """Purge all keys.  Useful between test runs."""
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


# ---------------------------------------------------------------------------
# Redis store (optional, requires redis-py)
# ---------------------------------------------------------------------------

class RedisStore(IdempotencyStore):
    """Redis-backed idempotency store using SET-NX.

    Book reference: Chapter 8, §8.5 — "RedisStore for Production"

    Args:
        client: A ``redis.Redis`` instance (or any compatible client).
        ttl_seconds: Key expiry.  Defaults to 86400 (24 hours).
    """

    def __init__(self, client: Any, ttl_seconds: int = 86_400) -> None:
        self._client = client
        self._ttl = ttl_seconds

    def set_if_absent(self, key: str, value: str) -> bool:
        result = self._client.set(key, value, nx=True, ex=self._ttl)
        return result is not None  # None means key already existed

    def get(self, key: str) -> str | None:
        raw = self._client.get(key)
        return raw.decode() if raw is not None else None


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class IdempotencyMiddleware:
    """Wraps tool invocations with idempotency guarantees.

    Book reference: Chapter 8, §8.2 — "The Middleware Pattern"

    Args:
        store: Any :class:`IdempotencyStore` implementation.
    """

    def __init__(self, store: IdempotencyStore) -> None:
        self._store = store

    def call(
        self,
        tool: MCPToolContract,
        inputs: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> Result[dict[str, Any], Exception]:
        """Execute *tool* with *inputs*, skipping if already completed.

        If *idempotency_key* is ``None``, the tool's own fingerprint is used
        as the key (SHA-256 of tool name + inputs).

        Args:
            tool: The tool to execute.
            inputs: Raw (unvalidated) inputs passed through to ``tool.call()``.
            idempotency_key: Optional explicit key.  Use explicit keys when the
                same logical operation might differ in argument representation
                (e.g. timestamps rounded differently).

        Returns:
            Cached :class:`~multiagent_orchestration.result.Ok` if previously
            completed, or the result of ``tool.call(inputs)`` for a fresh run.
        """
        key = idempotency_key or tool.fingerprint(inputs)
        result_key = key + ":result"

        # ── Phase 1: check for a previously completed result ────────────────
        # result_key is only written after a successful execution, so its
        # presence unambiguously means the operation already completed.
        existing = self._store.get(result_key)
        if existing is not None:
            try:
                cached = json.loads(existing)
                return Ok(cached)
            except json.JSONDecodeError:
                pass  # Corrupt cache entry — fall through to re-execute.

        # ── Phase 2: claim the lock key ─────────────────────────────────────
        # SET-NX on the primary key acts as a distributed lock.
        # If set_if_absent returns False, another in-flight call already holds
        # the lock.  We still execute here (simple implementation); a
        # production system would wait or fail fast.
        sentinel = json.dumps({"__pending": True})
        self._store.set_if_absent(key, sentinel)

        # ── Phase 3: execute ────────────────────────────────────────────────
        result = tool.call(inputs)

        if isinstance(result, Ok):
            # Store the result under result_key so future calls find it in Phase 1.
            self._store.set_if_absent(result_key, json.dumps(result.value))

        return result
