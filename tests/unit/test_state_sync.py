"""
tests/unit/test_state_sync.py
Book reference: Chapter 12 (Advanced)
"""

from __future__ import annotations

import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

import pytest

from multiagent_orchestration.state_sync import (
    AgentEvent,
    ConcurrentWriteError,
    DuplicateEventError,
    InMemoryEventStore,
)


class TestInMemoryEventStore:

    def setup_method(self):
        self.store = InMemoryEventStore()

    # ── Basic append ───────────────────────────────────────────────────────

    def test_append_returns_stored_event_with_version_1(self):
        event = AgentEvent(
            agent_id="planner",
            event_type="query_received",
            payload={"query": "test"},
            expected_version=0,
        )
        stored = self.store.append(event)
        assert stored.version == 1
        assert stored.event_type == "query_received"
        assert stored.payload == {"query": "test"}

    def test_sequential_appends_increment_version(self):
        for i in range(3):
            self.store.append(AgentEvent(
                agent_id="agent_a",
                event_type="step",
                payload={"i": i},
                expected_version=i,
            ))
        assert self.store.current_version("agent_a") == 3

    def test_current_version_zero_for_new_agent(self):
        assert self.store.current_version("nobody") == 0

    # ── Optimistic concurrency ─────────────────────────────────────────────

    def test_wrong_expected_version_raises_concurrent_write_error(self):
        self.store.append(AgentEvent(
            agent_id="agent_b",
            event_type="init",
            payload={},
            expected_version=0,
        ))
        with pytest.raises(ConcurrentWriteError) as exc_info:
            self.store.append(AgentEvent(
                agent_id="agent_b",
                event_type="conflict",
                payload={},
                expected_version=0,   # should be 1 now
            ))
        assert exc_info.value.expected == 0
        assert exc_info.value.actual == 1

    def test_concurrent_writers_only_one_wins(self):
        results = []
        barrier = threading.Barrier(2)

        def writer(payload_text):
            barrier.wait()
            try:
                e = self.store.append(AgentEvent(
                    agent_id="shared",
                    event_type="write",
                    payload={"text": payload_text},
                    expected_version=0,
                ))
                results.append(("ok", e.version))
            except ConcurrentWriteError:
                results.append(("conflict",))

        threads = [
            threading.Thread(target=writer, args=(f"writer-{i}",))
            for i in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        ok_count = sum(1 for r in results if r[0] == "ok")
        conflict_count = sum(1 for r in results if r[0] == "conflict")
        assert ok_count == 1
        assert conflict_count == 1
        assert self.store.current_version("shared") == 1

    # ── Exactly-once (duplicate event IDs) ────────────────────────────────

    def test_duplicate_event_id_raises(self):
        event = AgentEvent(
            agent_id="agent_c",
            event_type="step",
            payload={},
            expected_version=0,
            event_id="fixed-id-001",
        )
        self.store.append(event)
        with pytest.raises(DuplicateEventError) as exc_info:
            self.store.append(AgentEvent(
                agent_id="agent_c",
                event_type="step",
                payload={"different": True},
                expected_version=1,
                event_id="fixed-id-001",  # same ID — rejected
            ))
        assert exc_info.value.event_id == "fixed-id-001"

    # ── Replay / projection ────────────────────────────────────────────────

    def test_replay_reconstructs_state_by_merging_payloads(self):
        for i, payload in enumerate([
            {"query": "initial"},
            {"status": "searching"},
            {"result": "found it"},
        ]):
            self.store.append(AgentEvent(
                agent_id="agent_d",
                event_type="update",
                payload=payload,
                expected_version=i,
            ))
        state = self.store.replay("agent_d")
        assert state == {
            "query": "initial",
            "status": "searching",
            "result": "found it",
        }

    def test_replay_since_version_skips_earlier_events(self):
        for i, payload in enumerate([{"a": 1}, {"b": 2}, {"c": 3}]):
            self.store.append(AgentEvent(
                agent_id="agent_e",
                event_type="step",
                payload=payload,
                expected_version=i,
            ))
        state = self.store.replay("agent_e", since_version=1)
        assert "a" not in state   # version 1 skipped
        assert state["b"] == 2
        assert state["c"] == 3

    def test_replay_empty_agent_returns_empty_dict(self):
        assert self.store.replay("nonexistent") == {}

    # ── get_events ─────────────────────────────────────────────────────────

    def test_get_events_returns_all_events(self):
        for i in range(4):
            self.store.append(AgentEvent(
                agent_id="agent_f",
                event_type="step",
                payload={"i": i},
                expected_version=i,
            ))
        events = self.store.get_events("agent_f")
        assert len(events) == 4
        assert [e.version for e in events] == [1, 2, 3, 4]

    def test_get_events_since_version_filters_correctly(self):
        for i in range(5):
            self.store.append(AgentEvent(
                agent_id="agent_g",
                event_type="step",
                payload={"i": i},
                expected_version=i,
            ))
        events = self.store.get_events("agent_g", since_version=3)
        assert len(events) == 2
        assert events[0].version == 4
        assert events[1].version == 5

    # ── Multi-agent isolation ──────────────────────────────────────────────

    def test_different_agents_have_independent_logs(self):
        self.store.append(AgentEvent("alpha", "e", {}, 0))
        self.store.append(AgentEvent("alpha", "e", {}, 1))
        self.store.append(AgentEvent("beta", "e", {}, 0))
        assert self.store.current_version("alpha") == 2
        assert self.store.current_version("beta") == 1

    # ── Clear ──────────────────────────────────────────────────────────────

    def test_clear_resets_all_state(self):
        self.store.append(AgentEvent("x", "e", {}, 0))
        self.store.clear()
        assert self.store.current_version("x") == 0
        assert self.store.replay("x") == {}
