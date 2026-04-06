"""
semantic_loop_detector.py — SemanticLoopDetector
==================================================
Book reference: Chapter 15 — "Advanced Safety: Semantic Loop Detection"

The existing :class:`~multiagent_orchestration.loop_detector.InvocationFingerprinter`
catches **exact** argument repeats (SHA-256 of sorted JSON).  It is fast and
zero-dependency, but it misses **semantic** loops — cases where a misbehaving
agent re-invokes a tool with different phrasing but identical intent:

    Call 1: web_search(query="multi-agent orchestration patterns")
    Call 2: web_search(query="orchestration patterns for multi-agent systems")  ← not caught by SHA-256
    Call 3: web_search(query="patterns in multi agent orchestration")            ← not caught either

This module provides a second detection layer that compares incoming invocations
against a sliding window of recent ones using **cosine similarity** over
text embeddings.  When similarity exceeds a configurable threshold, a
:class:`SemanticLoopError` is raised before the tool executes.

Design decisions (see ARCHITECTURAL_DECISIONS.md §ADR-010):

- **Pluggable embedder** — the :class:`EmbedderBase` ABC accepts any embedding
  function.  The default :class:`TFIDFEmbedder` uses stdlib ``math`` and a
  character n-gram TF-IDF vector; it is deterministic and zero-dependency.
  Swap in OpenAI ``text-embedding-3-small`` or a local SentenceTransformer
  by writing one 10-line subclass.
- **Sliding window** — only the last ``window_size`` (default: 10) invocations
  are compared; this bounds memory and runtime.
- **Threshold** — cosine similarity ≥ ``threshold`` (default: 0.85) triggers
  detection.  Lower values catch looser paraphrases; higher values only flag
  near-identical intent.
- **Composable with the SHA-256 fingerprinter** — use both in the same pipeline:
  the SHA-256 check is O(1) and catches exact repeats cheaply; the semantic check
  runs only when the SHA-256 check passes.

Usage (Chapter 15, Listing 15.2)::

    from multiagent_orchestration.loop_detector import InvocationFingerprinter
    from multiagent_orchestration.semantic_loop_detector import SemanticLoopDetector

    # Layer 1: exact fingerprint (O(1))
    exact = InvocationFingerprinter(max_repeats=1)

    # Layer 2: semantic similarity (O(window_size))
    semantic = SemanticLoopDetector(threshold=0.85, window_size=10)

    for tool, inputs in pipeline_steps:
        exact.record(tool, inputs)          # raises LoopError on exact repeat
        semantic.record(tool, inputs)       # raises SemanticLoopError on near-duplicate
        result = tool.call(inputs)
"""

from __future__ import annotations

import abc
import json
import math
from collections import Counter, deque
from typing import Any

from multiagent_orchestration.contracts import MCPToolContract


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SemanticLoopError(Exception):
    """Raised when a tool invocation is semantically similar to a recent one.

    Book reference: Chapter 15, §15.3 — "The SemanticLoopError Contract"

    Attributes:
        tool_name: Tool that triggered the detection.
        similarity: Cosine similarity score (0.0–1.0).
        threshold: The configured threshold that was exceeded.
        matched_text: The earlier invocation text that was too similar.
    """

    def __init__(
        self,
        tool_name: str,
        similarity: float,
        threshold: float,
        matched_text: str,
    ) -> None:
        self.tool_name = tool_name
        self.similarity = similarity
        self.threshold = threshold
        self.matched_text = matched_text
        super().__init__(
            f"Semantic loop detected for tool '{tool_name}': "
            f"similarity {similarity:.3f} >= threshold {threshold:.3f}. "
            f"Matched: '{matched_text[:80]}…'"
        )


# ---------------------------------------------------------------------------
# Embedder abstraction
# ---------------------------------------------------------------------------

class EmbedderBase(abc.ABC):
    """Abstract base for text embedding functions.

    Book reference: Chapter 15, §15.4 — "The Pluggable Embedder Pattern"
    """

    @abc.abstractmethod
    def embed(self, text: str) -> list[float]:
        """Return a fixed-length embedding vector for *text*.

        The vector does not need to be unit-normalised; cosine similarity
        normalises internally.
        """


class TFIDFEmbedder(EmbedderBase):
    """Character n-gram TF-IDF embedder — zero external dependencies.

    Book reference: Chapter 15, §15.5 — "TFIDFEmbedder for Testing and Dev"

    Represents text as a sparse TF-IDF vector over character n-grams
    (default: 2-grams and 3-grams).  Vocabulary is built incrementally
    from all texts seen so far.

    This is intentionally simple — it catches paraphrases that share
    vocabulary or root morphemes.  For production, swap in OpenAI
    ``text-embedding-3-small`` via :class:`OpenAIEmbedder`.

    Args:
        ngram_range: Tuple of (min_n, max_n) for character n-grams.
    """

    def __init__(self, ngram_range: tuple[int, int] = (2, 3)) -> None:
        self._min_n, self._max_n = ngram_range
        self._vocab: dict[str, int] = {}          # ngram → index
        self._idf: dict[str, float] = {}          # ngram → IDF weight
        self._doc_count: int = 0
        self._doc_freq: Counter[str] = Counter()  # ngram → document count

    def _ngrams(self, text: str) -> list[str]:
        text = text.lower()
        result = []
        for n in range(self._min_n, self._max_n + 1):
            result.extend(text[i: i + n] for i in range(len(text) - n + 1))
        return result

    def _update_vocab(self, text: str) -> None:
        grams = set(self._ngrams(text))
        self._doc_count += 1
        for g in grams:
            if g not in self._vocab:
                self._vocab[g] = len(self._vocab)
            self._doc_freq[g] += 1
        # Recompute IDF (log-smoothed)
        for g, df in self._doc_freq.items():
            self._idf[g] = math.log((1 + self._doc_count) / (1 + df)) + 1.0

    def embed(self, text: str) -> list[float]:
        self._update_vocab(text)
        grams = self._ngrams(text)
        if not grams:
            return [0.0] * max(len(self._vocab), 1)

        tf: Counter[str] = Counter(grams)
        total = sum(tf.values())

        vec = [0.0] * len(self._vocab)
        for gram, count in tf.items():
            if gram in self._vocab:
                tf_val = count / total
                idf_val = self._idf.get(gram, 1.0)
                vec[self._vocab[gram]] = tf_val * idf_val

        return vec


class OpenAIEmbedder(EmbedderBase):
    """OpenAI embedding adapter.

    Book reference: Chapter 15, §15.6 — "Production Embedder via OpenAI"

    Requires: ``pip install "multiagent-orchestration[openai]"``

    Args:
        model: Embedding model name.  Default: ``"text-embedding-3-small"``.
        api_key: Falls back to ``OPENAI_API_KEY`` env var.
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
    ) -> None:
        try:
            import openai
        except ImportError as exc:
            raise ImportError(
                "OpenAIEmbedder requires openai. "
                "Install with: pip install 'multiagent-orchestration[openai]'"
            ) from exc
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model

    def embed(self, text: str) -> list[float]:
        response = self._client.embeddings.create(input=[text], model=self._model)
        return response.data[0].embedding


# ---------------------------------------------------------------------------
# Cosine similarity utility
# ---------------------------------------------------------------------------

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return cosine similarity between vectors *a* and *b*.

    Pads the shorter vector with zeros if lengths differ (can happen when
    TFIDFEmbedder's vocabulary grows between calls).
    """
    # Pad to equal length
    max_len = max(len(a), len(b))
    if len(a) < max_len:
        a = a + [0.0] * (max_len - len(a))
    if len(b) < max_len:
        b = b + [0.0] * (max_len - len(b))

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Semantic loop detector
# ---------------------------------------------------------------------------

class SemanticLoopDetector:
    """Detects semantically similar tool invocations using embedding cosine similarity.

    Book reference: Chapter 15, §15.2 — "The SemanticLoopDetector"

    Each instance is scoped to a **single pipeline run** — create a new
    instance per run, just like :class:`InvocationFingerprinter`.

    Args:
        threshold: Cosine similarity threshold (0.0–1.0) above which an
            invocation is considered a semantic loop.  Default: ``0.85``.
        window_size: Number of recent invocations to compare against.
            Default: ``10``.
        embedder: :class:`EmbedderBase` implementation.  Defaults to
            :class:`TFIDFEmbedder` (zero external deps).
    """

    def __init__(
        self,
        threshold: float = 0.85,
        window_size: int = 10,
        embedder: EmbedderBase | None = None,
    ) -> None:
        if not 0.0 < threshold <= 1.0:
            raise ValueError("threshold must be in (0.0, 1.0]")
        if window_size < 1:
            raise ValueError("window_size must be >= 1")

        self._threshold = threshold
        self._window: deque[tuple[str, list[float]]] = deque(maxlen=window_size)
        self._embedder = embedder or TFIDFEmbedder()

    def _invocation_text(self, tool: MCPToolContract, inputs: dict[str, Any]) -> str:
        """Serialise a tool invocation to a canonical string for embedding."""
        return f"{tool.name}: {json.dumps(inputs, sort_keys=True)}"

    def record(self, tool: MCPToolContract, inputs: dict[str, Any]) -> float | None:
        """Record an invocation and check for semantic similarity.

        Args:
            tool: The tool about to be called.
            inputs: The validated inputs.

        Returns:
            The highest similarity score seen against the window, or ``None``
            if the window was empty.

        Raises:
            SemanticLoopError: If similarity to any recent invocation
                exceeds :attr:`threshold`.
        """
        text = self._invocation_text(tool, inputs)
        vec = self._embedder.embed(text)

        max_sim: float | None = None
        max_text: str = ""

        for prev_text, prev_vec in self._window:
            sim = _cosine_similarity(vec, prev_vec)
            if max_sim is None or sim > max_sim:
                max_sim = sim
                max_text = prev_text

        if max_sim is not None and max_sim >= self._threshold:
            raise SemanticLoopError(
                tool_name=tool.name,
                similarity=max_sim,
                threshold=self._threshold,
                matched_text=max_text,
            )

        self._window.append((text, vec))
        return max_sim

    def reset(self) -> None:
        """Clear the sliding window.  Call between pipeline runs."""
        self._window.clear()

    @property
    def window_size(self) -> int:
        """Configured maximum window size."""
        return self._window.maxlen  # type: ignore[return-value]

    @property
    def current_window_length(self) -> int:
        """Number of invocations currently in the window."""
        return len(self._window)


# ---------------------------------------------------------------------------
# Composite detector (exact + semantic in one call)
# ---------------------------------------------------------------------------

class CompositeLoopDetector:
    """Runs exact SHA-256 fingerprint check then semantic similarity check.

    Book reference: Chapter 15, §15.7 — "Layered Detection Strategy"

    Use this as a drop-in replacement for :class:`InvocationFingerprinter`
    when semantic loop safety is needed.  The exact check is O(1) and runs
    first; the semantic check only runs when the exact check passes.

    Args:
        max_repeats: Forwarded to the exact fingerprinter.
        semantic_threshold: Forwarded to the semantic detector.
        window_size: Forwarded to the semantic detector.
        embedder: Optional custom embedder.
    """

    def __init__(
        self,
        max_repeats: int = 1,
        semantic_threshold: float = 0.85,
        window_size: int = 10,
        embedder: EmbedderBase | None = None,
    ) -> None:
        from multiagent_orchestration.loop_detector import InvocationFingerprinter
        self._exact = InvocationFingerprinter(max_repeats=max_repeats)
        self._semantic = SemanticLoopDetector(
            threshold=semantic_threshold,
            window_size=window_size,
            embedder=embedder,
        )

    def record(self, tool: MCPToolContract, inputs: dict[str, Any]) -> str:
        """Run both checks.  Raises :class:`LoopError` or :class:`SemanticLoopError`.

        Returns:
            The SHA-256 fingerprint string (same as ``InvocationFingerprinter``).
        """
        fp = self._exact.record(tool, inputs)   # raises LoopError if exact repeat
        self._semantic.record(tool, inputs)      # raises SemanticLoopError if similar
        return fp

    def reset(self) -> None:
        self._exact.reset()
        self._semantic.reset()
