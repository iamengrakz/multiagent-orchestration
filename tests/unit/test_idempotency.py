"""
tests/unit/test_idempotency.py
Book reference: Chapter 8
"""

from __future__ import annotations

import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

import threading

from multiagent_orchestration.contracts import MCPToolContract, ToolSchema
from multiagent_orchestration.idempotency import IdempotencyMiddleware, InMemoryStore
from multiagent_orchestration.result import Ok, Err


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_call_counter = 0


class CountingTool(MCPToolContract):
    """Records how many times execute() is actually called."""
    name = "counter"
    version = "1.0.0"
    description = "Counts real executions."
    side_effecting = True
    idempotent = True
    input_schema = ToolSchema(required=["n"], properties={"n": {"type": "integer"}})
    output_schema = ToolSchema(
        required=["count"],
        properties={"count": {"type": "integer"}},
    )

    def __init__(self):
        self.call_count = 0

    def execute(self, inputs):
        self.call_count += 1
        return {"count": self.call_count}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInMemoryStore:
    def test_set_if_absent_returns_true_first_time(self):
        store = InMemoryStore()
        assert store.set_if_absent("k", "v") is True

    def test_set_if_absent_returns_false_second_time(self):
        store = InMemoryStore()
        store.set_if_absent("k", "v")
        assert store.set_if_absent("k", "v2") is False

    def test_get_returns_value(self):
        store = InMemoryStore()
        store.set_if_absent("k", "hello")
        assert store.get("k") == "hello"

    def test_get_missing_returns_none(self):
        assert InMemoryStore().get("missing") is None

    def test_clear_empties_store(self):
        store = InMemoryStore()
        store.set_if_absent("k", "v")
        store.clear()
        assert len(store) == 0

    def test_thread_safety(self):
        """Multiple threads competing for the same key; only one wins."""
        store = InMemoryStore()
        winners = []

        def try_set():
            if store.set_if_absent("shared", "val"):
                winners.append(threading.current_thread().name)

        threads = [threading.Thread(target=try_set) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(winners) == 1


class TestIdempotencyMiddleware:
    def test_first_call_executes_tool(self):
        store = InMemoryStore()
        mw = IdempotencyMiddleware(store)
        tool = CountingTool()
        result = mw.call(tool, {"n": 1}, idempotency_key="run-001")
        assert isinstance(result, Ok)
        assert tool.call_count == 1

    def test_second_call_with_same_key_does_not_re_execute(self):
        store = InMemoryStore()
        mw = IdempotencyMiddleware(store)
        tool = CountingTool()
        mw.call(tool, {"n": 1}, idempotency_key="run-002")
        mw.call(tool, {"n": 1}, idempotency_key="run-002")
        # execute() should only have been called once
        assert tool.call_count == 1

    def test_different_keys_both_execute(self):
        store = InMemoryStore()
        mw = IdempotencyMiddleware(store)
        tool = CountingTool()
        mw.call(tool, {"n": 1}, idempotency_key="run-A")
        mw.call(tool, {"n": 1}, idempotency_key="run-B")
        assert tool.call_count == 2

    def test_fingerprint_used_when_no_explicit_key(self):
        store = InMemoryStore()
        mw = IdempotencyMiddleware(store)
        tool = CountingTool()
        inputs = {"n": 42}
        mw.call(tool, inputs)  # no explicit key → uses fingerprint
        mw.call(tool, inputs)  # same fingerprint
        assert tool.call_count == 1
