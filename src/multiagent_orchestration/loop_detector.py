"""
loop_detector.py — InvocationFingerprinter
==========================================
Book reference: Chapter 6, §6.1–6.4

Detects when the orchestrator is about to invoke a tool with the exact same
arguments it has already used in the current pipeline run — the root cause of
infinite agentic loops.

The fingerprint is a SHA-256 hex digest of ``json.dumps({"tool": name,
"inputs": inputs}, sort_keys=True)``.  Sort-key normalisation ensures that
argument ordering differences do not produce false negatives.

Book pattern output marker (Chapter 6)::

    🔁  LOOP PREVENTED — orchestrator terminated before infinite tool call ✓

Usage (Chapter 6, Listing 6.2)::

    detector = InvocationFingerprinter(max_repeats=1)

    for tool in pipeline:
        try:
            detector.record(tool, inputs)
        except LoopError as exc:
            logger.error("loop_detected", fingerprint=exc.fingerprint)
            break   # halt the pipeline
        result = tool.call(inputs)
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from multiagent_orchestration.contracts import MCPToolContract


class LoopError(Exception):
    """Raised when a repeated invocation fingerprint is detected.

    Book reference: Chapter 6, §6.3 — "The LoopError Contract"

    Attributes:
        tool_name: Name of the tool that triggered the detection.
        fingerprint: SHA-256 hex digest of the repeated invocation.
        occurrences: How many times this fingerprint has been seen so far.
    """

    def __init__(self, tool_name: str, fingerprint: str, occurrences: int) -> None:
        self.tool_name = tool_name
        self.fingerprint = fingerprint
        self.occurrences = occurrences
        super().__init__(
            f"Loop detected: tool '{tool_name}' invoked with identical arguments "
            f"{occurrences} time(s). Fingerprint: {fingerprint[:12]}…"
        )


class InvocationFingerprinter:
    """Records tool invocation fingerprints and raises on repeats.

    Book reference: Chapter 6, §6.2 — "The InvocationFingerprinter"

    Each instance is scoped to a **single pipeline run**.  Create a new
    instance for each run; do not share across runs.

    Args:
        max_repeats: How many times the same fingerprint may appear before
            :class:`LoopError` is raised.  Defaults to ``1`` (any repetition
            is an error).  Set to a higher value only if your pipeline
            legitimately re-invokes the same tool with the same args
            (rare, and a design smell).
    """

    def __init__(self, max_repeats: int = 1) -> None:
        if max_repeats < 1:
            raise ValueError("max_repeats must be >= 1")
        self._max_repeats = max_repeats
        self._seen: dict[str, int] = defaultdict(int)  # fingerprint → count

    def record(self, tool: MCPToolContract, inputs: dict[str, Any]) -> str:
        """Record an invocation and raise if the fingerprint repeats.

        Args:
            tool: The tool about to be called.
            inputs: The validated input dict.

        Returns:
            The fingerprint string (useful for logging).

        Raises:
            LoopError: If the fingerprint has already been seen
                ``max_repeats`` times.
        """
        fp = tool.fingerprint(inputs)
        self._seen[fp] += 1
        count = self._seen[fp]
        if count > self._max_repeats:
            raise LoopError(
                tool_name=tool.name,
                fingerprint=fp,
                occurrences=count,
            )
        return fp

    def reset(self) -> None:
        """Clear all recorded fingerprints.  Call between pipeline runs."""
        self._seen.clear()

    @property
    def unique_invocations(self) -> int:
        """Number of distinct tool+arg combinations seen so far."""
        return len(self._seen)

    @property
    def total_invocations(self) -> int:
        """Total number of invocations recorded (including repeats)."""
        return sum(self._seen.values())
