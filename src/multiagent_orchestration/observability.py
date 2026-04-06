"""
observability.py — StructuredLogger, Span, Trace
==================================================
Book reference: Chapter 9, §9.1–9.5

Produces newline-delimited JSON (NDJSON) events to stdout (or any file-like
object), compatible with Datadog, OpenTelemetry Collector, AWS CloudWatch
Logs Insights, and most other log aggregators.

Every event carries:

- ``trace_id``: UUID4 generated once per pipeline run.
- ``span_id``: UUID4 for each individual tool invocation span.
- ``level``: ``"DEBUG"`` | ``"INFO"`` | ``"WARN"`` | ``"ERROR"``.
- ``event``: Snake-case event name (e.g. ``"tool_call_start"``).
- ``timestamp_ms``: Unix epoch milliseconds.
- Arbitrary keyword arguments merged into the top-level JSON object.

When a ``BOOK_PATTERN`` tag is present, the event is also printed to stderr
as a human-readable highlighted line — useful during example runs.

Usage (Chapter 9, Listing 9.1)::

    logger = StructuredLogger(verbose=True)

    with logger.span("web_search", trace_id=run_id) as span:
        result = tool.call(inputs)
        span.set_status("ok" if result.is_ok() else "error")
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from io import TextIOBase
from typing import Any, Generator


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Span:
    """Represents a single timed operation within a trace.

    Book reference: Chapter 9, §9.3 — "Spans and Traces"
    """

    span_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    start_ms: int = field(default_factory=_now_ms)
    end_ms: int | None = None
    status: str = "ok"
    tags: dict[str, Any] = field(default_factory=dict)

    def set_status(self, status: str) -> None:
        self.status = status

    def finish(self) -> None:
        self.end_ms = _now_ms()

    @property
    def duration_ms(self) -> int | None:
        if self.end_ms is None:
            return None
        return self.end_ms - self.start_ms


class StructuredLogger:
    """Emits NDJSON event lines suitable for any log aggregator.

    Book reference: Chapter 9, §9.2 — "The StructuredLogger Design"

    Args:
        verbose: When ``True``, also prints highlighted human-readable lines
            to stderr for ``BOOK_PATTERN``-tagged events.  Defaults to
            ``False``.
        stream: Output stream.  Defaults to ``sys.stdout``.
    """

    def __init__(
        self,
        verbose: bool = False,
        stream: TextIOBase | None = None,
    ) -> None:
        self._verbose = verbose
        self._stream = stream or sys.stdout

    # ------------------------------------------------------------------
    # Emit helpers
    # ------------------------------------------------------------------

    def info(self, event: str, **kwargs: Any) -> None:
        self._emit("INFO", event, **kwargs)

    def warn(self, event: str, **kwargs: Any) -> None:
        self._emit("WARN", event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._emit("ERROR", event, **kwargs)

    def debug(self, event: str, **kwargs: Any) -> None:
        self._emit("DEBUG", event, **kwargs)

    def book_pattern(self, message: str, **kwargs: Any) -> None:
        """Emit an event tagged as a book pattern demonstration.

        Book reference: Chapter 9, §9.4 — "BOOK_PATTERN Tagging"

        This always prints the human-readable marker to stderr regardless
        of ``verbose`` mode.
        """
        self._emit("INFO", "book_pattern_triggered", tag="BOOK_PATTERN",
                   message=message, **kwargs)
        print(f"\n  {message}\n", file=sys.stderr)

    # ------------------------------------------------------------------
    # Span context manager
    # ------------------------------------------------------------------

    @contextmanager
    def span(
        self, name: str, trace_id: str | None = None, **tags: Any
    ) -> Generator[Span, None, None]:
        """Context manager that emits ``span_start`` and ``span_end`` events.

        Args:
            name: Logical name of the operation (e.g. ``"web_search"``).
            trace_id: Shared trace ID for the current pipeline run.
            **tags: Arbitrary key-value metadata merged into both events.
        """
        s = Span(
            name=name,
            trace_id=trace_id or str(uuid.uuid4()),
            tags=tags,
        )
        self._emit(
            "INFO",
            "span_start",
            span_id=s.span_id,
            trace_id=s.trace_id,
            span_name=name,
            **tags,
        )
        try:
            yield s
        except Exception as exc:
            s.set_status("error")
            self._emit(
                "ERROR",
                "span_error",
                span_id=s.span_id,
                trace_id=s.trace_id,
                span_name=name,
                error=str(exc),
                **tags,
            )
            raise
        finally:
            s.finish()
            self._emit(
                "INFO",
                "span_end",
                span_id=s.span_id,
                trace_id=s.trace_id,
                span_name=name,
                status=s.status,
                duration_ms=s.duration_ms,
                **tags,
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _emit(self, level: str, event: str, **kwargs: Any) -> None:
        record = {
            "timestamp_ms": _now_ms(),
            "level": level,
            "event": event,
            **kwargs,
        }
        line = json.dumps(record, default=str)
        print(line, file=self._stream, flush=True)

        if self._verbose and kwargs.get("tag") == "BOOK_PATTERN":
            print(f"[BOOK_PATTERN] {event}: {kwargs.get('message', '')}", file=sys.stderr)
