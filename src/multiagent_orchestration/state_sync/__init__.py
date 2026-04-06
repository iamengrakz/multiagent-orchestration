"""
state_sync — Event-sourced state synchronisation for distributed agent fleets.

Book reference: Chapter 12 (Advanced)

Public API::

    from multiagent_orchestration.state_sync import (
        AgentEvent,
        StoredEvent,
        InMemoryEventStore,
        RedisEventStore,
        ConcurrentWriteError,
        DuplicateEventError,
    )
"""

from multiagent_orchestration.state_sync.event_store import (
    AgentEvent,
    StoredEvent,
    InMemoryEventStore,
    RedisEventStore,
    ConcurrentWriteError,
    DuplicateEventError,
)

__all__ = [
    "AgentEvent",
    "StoredEvent",
    "InMemoryEventStore",
    "RedisEventStore",
    "ConcurrentWriteError",
    "DuplicateEventError",
]
