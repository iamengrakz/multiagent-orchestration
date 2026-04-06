"""
contracts.py — MCPToolContract and ToolSchema
=============================================
Book reference: Chapters 2 and 3

``MCPToolContract`` is the central abstraction of this library.  Every agent
capability — web search, database lookup, email dispatch, market data fetch —
is expressed as a subclass of ``MCPToolContract``.  This achieves three things:

1. **Decoupling**: orchestrator logic never imports concrete tool classes.
2. **Schema validation**: input/output are validated against JSON Schema before
   and after ``execute()`` is called.
3. **Versioning**: tools carry a semantic version string; the orchestrator can
   refuse to schedule a tool whose version is incompatible with the pipeline.

Usage (Chapter 2, Listing 2.3)::

    class WebSearchTool(MCPToolContract):
        name = "web_search"
        version = "1.0.0"
        description = "Search the web and return a list of results."
        input_schema = ToolSchema(
            required=["query"],
            properties={
                "query": {"type": "string", "minLength": 1, "maxLength": 512},
                "max_results": {"type": "integer", "default": 5, "maximum": 20},
            },
        )
        output_schema = ToolSchema(
            required=["results"],
            properties={
                "results": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        )

        def execute(self, inputs: dict) -> dict:
            # swap this body for a real API call
            query = inputs["query"]
            return {"results": [f"[stub] result for '{query}'"]}
"""

from __future__ import annotations

import abc
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from multiagent_orchestration._validator import validate_schema, _ValidationError as _ValErr
from multiagent_orchestration.result import Ok, Err, Result


# ---------------------------------------------------------------------------
# ToolSchema
# ---------------------------------------------------------------------------

@dataclass
class ToolSchema:
    """Thin wrapper around a JSON Schema object.

    Book reference: Chapter 2, §2.2 — "Schema as Contract"

    Args:
        required: List of required property names.
        properties: Mapping of property name → JSON Schema sub-object.
        additional_properties: Whether undeclared keys are allowed in validated
            data.  Defaults to ``False`` to enforce strict contracts.
    """

    required: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    additional_properties: bool = False

    def as_json_schema(self) -> dict[str, Any]:
        """Return a plain dict that ``jsonschema.validate`` can consume."""
        return {
            "type": "object",
            "required": self.required,
            "properties": self.properties,
            "additionalProperties": self.additional_properties,
        }

    def validate(self, data: dict[str, Any]) -> None:
        """Raise :class:`ValidationError` if *data* violates the schema.

        Args:
            data: The dict to validate.

        Raises:
            ValidationError: On the first schema violation.
        """
        try:
            validate_schema(self.as_json_schema(), data)
        except _ValErr as exc:
            raise ValidationError(str(exc)) from exc


# ---------------------------------------------------------------------------
# ValidationError
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    """Raised when a tool's input or output fails schema validation.

    Book reference: Chapter 3, §3.1 — "Fail Fast at the Contract Boundary"
    """


# ---------------------------------------------------------------------------
# MCPToolContract
# ---------------------------------------------------------------------------

class MCPToolContract(abc.ABC):
    """Abstract base class for every tool in the multi-agent system.

    Book reference: Chapter 2, §2.3 — "The MCPToolContract Interface"

    Subclasses **must** define:

    - :attr:`name` — snake_case unique identifier used by the orchestrator.
    - :attr:`version` — semantic version string (``"MAJOR.MINOR.PATCH"``).
    - :attr:`description` — human-readable description (surfaced in LLM prompts).
    - :attr:`input_schema` — :class:`ToolSchema` describing expected inputs.
    - :attr:`output_schema` — :class:`ToolSchema` describing expected outputs.
    - :meth:`execute` — the actual implementation.

    Subclasses **may** override:

    - :attr:`retry_policy` — a :class:`~multiagent_orchestration.retry.RetryPolicy`
      instance; defaults to no retries.
    - :attr:`idempotent` — set to ``True`` to enable idempotency middleware
      (Chapter 8).
    - :attr:`side_effecting` — set to ``True`` to signal that ``execute()``
      has observable external side effects (used by the circuit breaker,
      Chapter 10).
    """

    # ------------------------------------------------------------------
    # Class-level contract attributes — must be overridden by subclasses
    # ------------------------------------------------------------------

    name: str
    version: str
    description: str
    input_schema: ToolSchema
    output_schema: ToolSchema

    # Optional overrides
    idempotent: bool = False
    side_effecting: bool = False

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Run the tool and return a plain dict matching ``output_schema``.

        Do **not** call this directly in orchestrator code.  Always go through
        :meth:`call`, which handles validation, observability, and middleware.

        Args:
            inputs: Validated input dict (schema already checked).

        Returns:
            Output dict (schema will be checked after return).

        Raises:
            Any exception — the orchestrator wraps it in :class:`~multiagent_orchestration.result.Err`.
        """

    def call(self, inputs: dict[str, Any]) -> Result[dict[str, Any], Exception]:
        """Validate inputs, run :meth:`execute`, validate outputs.

        Book reference: Chapter 2, §2.4 — "The call() Wrapper Pattern"

        This is the method the orchestrator calls.  It:

        1. Validates ``inputs`` against :attr:`input_schema`.
        2. Calls :meth:`execute`.
        3. Validates the output against :attr:`output_schema`.
        4. Returns :class:`~multiagent_orchestration.result.Ok` on success or
           :class:`~multiagent_orchestration.result.Err` on any failure.

        Args:
            inputs: Raw input dict (not yet validated).

        Returns:
            A :class:`~multiagent_orchestration.result.Result` discriminated union.
        """
        try:
            self.input_schema.validate(inputs)
        except ValidationError as exc:
            return Err(exc)

        try:
            raw_output = self.execute(inputs)
        except Exception as exc:  # noqa: BLE001
            return Err(exc)

        try:
            self.output_schema.validate(raw_output)
        except ValidationError as exc:
            return Err(exc)

        return Ok(raw_output)

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def fingerprint(self, inputs: dict[str, Any]) -> str:
        """Return a stable hex digest of ``(name, inputs)``.

        Used by :class:`~multiagent_orchestration.loop_detector.InvocationFingerprinter`
        to detect repeated invocations with identical arguments.

        Book reference: Chapter 6, §6.2 — "Fingerprinting Invocations"
        """
        payload = json.dumps(
            {"tool": self.name, "inputs": inputs}, sort_keys=True
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.__class__.__name__} name={self.name!r} version={self.version!r}>"
