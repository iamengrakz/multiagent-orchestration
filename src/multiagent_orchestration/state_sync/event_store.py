"""
state_sync/event_store.py — Event-Sourced Agent State Store
=============================================================
Book reference: Chapter 12 (Advanced) — "State Synchronisation Across Distributed Agents"

The editor's report identified this as the single biggest missing pattern:

    "Most agent fleets fail not at the single-tool level but when agents in
     different regions/clouds diverge on shared world state."

This module provides a minimal event-sourced store with exactly-once semantics
for shared agent state.  Every state mutation is an immutable **event** appended
to an **event log** rather than an in-place update.  Any agent can reconstruct
current world state by replaying the log from the beginning — or from a snapshot.

Design principles (see ARCHITECTURAL_DECISIONS.md §ADR-009):

- **Append-only log** — mutations never overwrite; every transition is auditable.
- **Optimistic concurrency** — each append carries the expected log version; a
  mismatch raises ``ConcurrentWriteError`` rather than silently clobbering.
- **Exactly-once delivery** — events carry a UUID ``event_id``; the store
  rejects duplicate IDs (same SET-NX pattern as idempotency middleware).
- **Snapshot support** — large logs can be compacted; replay starts from the
  most recent snapshot + trailing events.
- **Pluggable backend** — ``InMemoryEventStore`` (zero deps, for tests/dev)
  and a ``RedisEventStore`` stub are provided.

Usage (Chapter 12 Listing 12.3)::

    store = InMemoryEventStore()

    # Agent A appends a state transition:
    store.append(AgentEvent(
        agent_id="planner",
        event_type="query_received",
        payload={"query": "multi-agent orchestration"},
        expected_version=0,       # optimistic lock: must be current version
    ))

    # Agent B reads current world state:
    state = store.replay("planner")
    print(state)   # {"query": "multi-agent orchestration"}

    # Conflict: Agent C tries to write at the same version — raises:
    store.append(AgentEvent(
        agent_id="planner",
        event_type="query_received",
        payload={"query": "other query"},
        expected_version=0,       # version already advanced to 1 → error
    ))
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

@dataclass
class AgentEvent:
    """A single immutable state-transition event for one agent.

    Attributes:
        agent_id: Identifies which agent's state this event belongs to.
        event_type: Snake-case descriptor, e.g. ``"query_received"``,
            ``"tool_called"``, ``"result_stored"``.
        payload: Arbitrary JSON-serialisable data for this transition.
        expected_version: The log version the writer believes is current.
            Used for optimistic concurrency control.
        event_id: Auto-generated UUID4; used for exactly-once deduplication.
    """

    agent_id: str
    event_type: str
    payload: dict[str, Any]
    expected_version: int = 0
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass(frozen=True)
class StoredEvent:
    """An event as persisted in the log (immutable once written).

    Attributes:
        event_id: Deduplication key.
        agent_id: Agent this event belongs to.
        event_type: Event descriptor.
        payload: State data.
        version: Monotonically increasing version number assigned by the store.
    """

    event_id: str
    agent_id: str
    event_type: str
    payload: dict[str, Any]
    version: int


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ConcurrentWriteError(Exception):
    """Raised when an append's ``expected_version`` does not match the current log version.

    Book reference: Chapter 12, §12.9 — "Optimistic Concurrency in Distributed Agents"

    Attributes:
        agent_id: The agent whose log had the conflict.
        expected: Version the writer expected.
        actual: Version the store currently holds.
    """

    def __init__(self, agent_id: str, expected: int, actual: int) -> None:
        self.agent_id = agent_id
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Concurrent write conflict for agent '{agent_id}': "
            f"expected version {expected}, actual version {actual}. "
            "Reload state and retry."
        )


class DuplicateEventError(Exception):
    """Raised when an event with an already-seen ``event_id`` is appended.

    Book reference: Chapter 12, §12.10 — "Exactly-Once Event Delivery"
    """

    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        super().__init__(
            f"Duplicate event rejected: event_id '{event_id}' already exists in the log."
        )


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------

class EventStore:
    """Abstract base for event store implementations.

    Concrete implementations: :class:`InMemoryEventStore`, :class:`RedisEventStore`.
    """

    def append(self, event: AgentEvent) -> StoredEvent:
        """Append *event* to the log with optimistic concurrency check.

        Args:
            event: The event to append.

        Returns:
            The stored event with its assigned version number.

        Raises:
            ConcurrentWriteError: If ``expected_version`` does not match current.
            DuplicateEventError: If ``event_id`` has already been appended.
        """
        raise NotImplementedError

    def get_events(self, agent_id: str, since_version: int = 0) -> list[StoredEvent]:
        """Return all events for *agent_id* with version > *since_version*.

        Args:
            agent_id: The agent to query.
            since_version: Return only events appended after this version.
                Use ``0`` (default) for a full replay.

        Returns:
            Ordered list of :class:`StoredEvent` instances.
        """
        raise NotImplementedError

    def current_version(self, agent_id: str) -> int:
        """Return the current log version for *agent_id* (0 if no events)."""
        raise NotImplementedError

    def replay(self, agent_id: str, since_version: int = 0) -> dict[str, Any]:
        """Reconstruct current state by replaying events.

        Each event's ``payload`` is merged (shallow) into the accumulated state
        in version order.  This is a simple fold; override for domain-specific
        projections.

        Args:
            agent_id: Agent whose state to reconstruct.
            since_version: Start replay from this version (for snapshot support).

        Returns:
            The current projected state as a plain dict.
        """
        state: dict[str, Any] = {}
        for event in self.get_events(agent_id, since_version=since_version):
            state.update(event.payload)
        return state


# ---------------------------------------------------------------------------
# In-memory implementation (zero deps — default for tests and dev)
# ---------------------------------------------------------------------------

class InMemoryEventStore(EventStore):
    """Thread-safe, in-memory event store.

    Book reference: Chapter 12, §12.8 — "InMemoryEventStore for Testing"

    Uses per-agent locks to allow concurrent appends by different agents
    while serialising writes to the same agent's log (mirrors the behaviour
    of a Redis stream with XADD).
    """

    def __init__(self) -> None:
        # agent_id → list of StoredEvent (ordered by version)
        self._logs: dict[str, list[StoredEvent]] = {}
        # global set of seen event_ids for exactly-once deduplication
        self._seen_event_ids: set[str] = set()
        # per-agent lock + a global lock for the seen-IDs set
        self._agent_locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

    # ------------------------------------------------------------------
    # EventStore interface
    # ------------------------------------------------------------------

    def append(self, event: AgentEvent) -> StoredEvent:
        agent_lock = self._get_agent_lock(event.agent_id)

        with agent_lock:
            # ── Exactly-once check ──────────────────────────────────────
            with self._global_lock:
                if event.event_id in self._seen_event_ids:
                    raise DuplicateEventError(event.event_id)

            # ── Optimistic concurrency check ────────────────────────────
            current = self._current_version_locked(event.agent_id)
            if event.expected_version != current:
                raise ConcurrentWriteError(
                    agent_id=event.agent_id,
                    expected=event.expected_version,
                    actual=current,
                )

            # ── Commit ──────────────────────────────────────────────────
            new_version = current + 1
            stored = StoredEvent(
                event_id=event.event_id,
                agent_id=event.agent_id,
                event_type=event.event_type,
                payload=dict(event.payload),
                version=new_version,
            )
            if event.agent_id not in self._logs:
                self._logs[event.agent_id] = []
            self._logs[event.agent_id].append(stored)

            with self._global_lock:
                self._seen_event_ids.add(event.event_id)

            return stored

    def get_events(self, agent_id: str, since_version: int = 0) -> list[StoredEvent]:
        with self._get_agent_lock(agent_id):
            log = self._logs.get(agent_id, [])
            return [e for e in log if e.version > since_version]

    def current_version(self, agent_id: str) -> int:
        with self._get_agent_lock(agent_id):
            return self._current_version_locked(agent_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _current_version_locked(self, agent_id: str) -> int:
        """Return current version; caller must hold the agent lock."""
        log = self._logs.get(agent_id, [])
        return log[-1].version if log else 0

    def _get_agent_lock(self, agent_id: str) -> threading.Lock:
        with self._global_lock:
            if agent_id not in self._agent_locks:
                self._agent_locks[agent_id] = threading.Lock()
            return self._agent_locks[agent_id]

    def all_agent_ids(self) -> list[str]:
        """Return all agent IDs that have at least one event."""
        return list(self._logs.keys())

    def clear(self) -> None:
        """Purge all logs and seen IDs.  Useful between test runs."""
        with self._global_lock:
            self._logs.clear()
            self._seen_event_ids.clear()
            self._agent_locks.clear()


# ---------------------------------------------------------------------------
# Redis-backed implementation (stub — requires redis-py)
# ---------------------------------------------------------------------------

class RedisEventStore(EventStore):
    """Redis Streams-backed event store for distributed deployments.

    Book reference: Chapter 12, §12.11 — "RedisEventStore for Production"

    Uses Redis Streams (XADD / XRANGE) which provide:
    - Ordered, append-only log per stream key.
    - Consumer groups for fan-out delivery.
    - Built-in message IDs that act as version numbers.

    Requires: ``pip install "multiagent-orchestration[redis]"``

    Args:
        client: A ``redis.Redis`` instance.
        key_prefix: Stream key prefix, e.g. ``"agent:events:"``.
    """

    def __init__(self, client: Any, key_prefix: str = "agent:events:") -> None:
        self._client = client
        self._prefix = key_prefix

    def _stream_key(self, agent_id: str) -> str:
        return f"{self._prefix}{agent_id}"

    def append(self, event: AgentEvent) -> StoredEvent:
        key = self._stream_key(event.agent_id)

        # Exactly-once: use a separate Redis key as a seen-IDs set.
        seen_key = f"{self._prefix}__seen_ids"
        added = self._client.sadd(seen_key, event.event_id)
        if not added:
            raise DuplicateEventError(event.event_id)

        # Optimistic concurrency: check stream length == expected_version.
        current = int(self._client.xlen(key))
        if event.expected_version != current:
            self._client.srem(seen_key, event.event_id)  # rollback
            raise ConcurrentWriteError(event.agent_id, event.expected_version, current)

        msg_id = self._client.xadd(key, {
            "event_id": event.event_id,
            "event_type": event.event_type,
            **{f"payload__{k}": str(v) for k, v in event.payload.items()},
        })
        new_version = current + 1
        return StoredEvent(
            event_id=event.event_id,
            agent_id=event.agent_id,
            event_type=event.event_type,
            payload=event.payload,
            version=new_version,
        )

    def get_events(self, agent_id: str, since_version: int = 0) -> list[StoredEvent]:
        key = self._stream_key(agent_id)
        # XRANGE returns all entries; we slice by since_version index.
        all_entries = self._client.xrange(key)
        result = []
        for i, (msg_id, fields) in enumerate(all_entries):
            version = i + 1
            if version <= since_version:
                continue
            payload = {
                k.decode().replace("payload__", ""): v.decode()
                for k, v in fields.items()
                if k.decode().startswith("payload__")
            }
            result.append(StoredEvent(
                event_id=fields.get(b"event_id", b"").decode(),
                agent_id=agent_id,
                event_type=fields.get(b"event_type", b"").decode(),
                payload=payload,
                version=version,
            ))
        return result

    def current_version(self, agent_id: str) -> int:
        return int(self._client.xlen(self._stream_key(agent_id)))
