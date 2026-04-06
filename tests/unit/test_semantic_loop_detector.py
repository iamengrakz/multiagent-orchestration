"""
tests/unit/test_semantic_loop_detector.py
Book reference: Chapter 15
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

import pytest

from multiagent_orchestration.contracts import MCPToolContract, ToolSchema
from multiagent_orchestration.loop_detector import LoopError
from multiagent_orchestration.semantic_loop_detector import (
    CompositeLoopDetector,
    SemanticLoopDetector,
    SemanticLoopError,
    TFIDFEmbedder,
    _cosine_similarity,
)


def make_tool(name: str) -> MCPToolContract:
    class T(MCPToolContract):
        input_schema = ToolSchema(required=[], properties={"query": {"type": "string"}})
        output_schema = ToolSchema(required=[], properties={})
        def execute(self, inputs): return {}
    T.name = name; T.version = "1.0.0"; T.description = name
    return T()


class TestCosineSimilarity:
    def test_identical_vectors_give_1(self):
        v = [1.0, 2.0, 3.0]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-9

    def test_orthogonal_vectors_give_0(self):
        assert abs(_cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-9

    def test_zero_vector_gives_0(self):
        assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_different_length_vectors_padded(self):
        # Should not raise; shorter vector is zero-padded
        sim = _cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0])
        assert abs(sim - 1.0) < 1e-9


class TestTFIDFEmbedder:
    def test_returns_nonempty_vector(self):
        emb = TFIDFEmbedder()
        v = emb.embed("hello world")
        assert len(v) > 0

    def test_identical_texts_have_perfect_similarity(self):
        emb = TFIDFEmbedder()
        v1 = emb.embed("multi-agent orchestration")
        v2 = emb.embed("multi-agent orchestration")
        assert abs(_cosine_similarity(v1, v2) - 1.0) < 1e-6

    def test_similar_texts_have_high_similarity(self):
        emb = TFIDFEmbedder()
        v1 = emb.embed("orchestration patterns for agents")
        v2 = emb.embed("agent orchestration patterns")
        sim = _cosine_similarity(v1, v2)
        assert sim > 0.5  # should be meaningfully similar

    def test_unrelated_texts_have_low_similarity(self):
        emb = TFIDFEmbedder()
        v1 = emb.embed("multi-agent orchestration")
        v2 = emb.embed("chocolate cake recipe")
        sim = _cosine_similarity(v1, v2)
        assert sim < 0.6


class TestSemanticLoopDetector:
    def setup_method(self):
        self.tool = make_tool("web_search")
        self.detector = SemanticLoopDetector(threshold=0.85, window_size=5)

    def test_first_call_returns_none(self):
        result = self.detector.record(self.tool, {"query": "hello"})
        assert result is None  # empty window

    def test_unrelated_calls_do_not_trigger(self):
        self.detector.record(self.tool, {"query": "multi-agent orchestration"})
        # Completely different topic — should not raise
        self.detector.record(self.tool, {"query": "chocolate cake recipe"})

    def test_exact_duplicate_triggers_semantic_error(self):
        self.detector.record(self.tool, {"query": "multi-agent orchestration patterns"})
        with pytest.raises(SemanticLoopError) as exc_info:
            self.detector.record(self.tool, {"query": "multi-agent orchestration patterns"})
        assert exc_info.value.tool_name == "web_search"
        assert exc_info.value.similarity >= 0.85

    def test_reset_clears_window(self):
        self.detector.record(self.tool, {"query": "multi-agent orchestration patterns"})
        self.detector.reset()
        # Should not raise after reset
        self.detector.record(self.tool, {"query": "multi-agent orchestration patterns"})

    def test_window_size_limits_comparisons(self):
        detector = SemanticLoopDetector(threshold=0.99, window_size=2)
        t = make_tool("t")
        detector.record(t, {"query": "aaa bbb ccc"})
        detector.record(t, {"query": "ddd eee fff"})
        detector.record(t, {"query": "ggg hhh iii"})
        # After 3 calls with window=2, the oldest ("aaa bbb ccc") is gone
        assert detector.current_window_length == 2

    def test_invalid_threshold_raises(self):
        with pytest.raises(ValueError):
            SemanticLoopDetector(threshold=0.0)
        with pytest.raises(ValueError):
            SemanticLoopDetector(threshold=1.5)

    def test_invalid_window_size_raises(self):
        with pytest.raises(ValueError):
            SemanticLoopDetector(window_size=0)

    def test_semantic_loop_error_attributes(self):
        self.detector.record(self.tool, {"query": "agent orchestration"})
        try:
            self.detector.record(self.tool, {"query": "agent orchestration"})
        except SemanticLoopError as exc:
            assert exc.tool_name == "web_search"
            assert 0.0 <= exc.similarity <= 1.0
            assert exc.threshold == 0.85
            assert isinstance(exc.matched_text, str)


class TestCompositeLoopDetector:
    def setup_method(self):
        self.tool = make_tool("search")

    def test_exact_repeat_raises_loop_error(self):
        detector = CompositeLoopDetector(max_repeats=1, semantic_threshold=0.99)
        detector.record(self.tool, {"query": "exact query"})
        with pytest.raises(LoopError):
            detector.record(self.tool, {"query": "exact query"})

    def test_returns_fingerprint_string(self):
        detector = CompositeLoopDetector()
        fp = detector.record(self.tool, {"query": "test"})
        assert isinstance(fp, str) and len(fp) == 64

    def test_reset_clears_both_detectors(self):
        detector = CompositeLoopDetector(max_repeats=1, semantic_threshold=0.99)
        detector.record(self.tool, {"query": "reset test"})
        detector.reset()
        # Should not raise after reset
        detector.record(self.tool, {"query": "reset test"})

    def test_unrelated_calls_pass_both_checks(self):
        detector = CompositeLoopDetector(semantic_threshold=0.85)
        detector.record(self.tool, {"query": "multi-agent orchestration"})
        detector.record(self.tool, {"query": "chocolate cake recipe"})
        detector.record(self.tool, {"query": "quantum physics overview"})
