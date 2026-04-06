"""
_validator.py — Lightweight stdlib JSON Schema validator
=========================================================
Book reference: Chapter 3, §3.1

A minimal JSON Schema validator covering the subset of keywords used by
MCPToolContract schemas:

    type, required, properties, additionalProperties,
    minLength, maxLength, minimum, maximum, items, default

This keeps the library dependency-free for the core validation path.
For full JSON Schema Draft-7 compliance in production, swap in ``jsonschema``
by setting ``MULTIAGENT_USE_JSONSCHEMA=1`` and installing it as an optional
extra (see pyproject.toml).

This module is internal.  Do not import it directly; use ``ToolSchema.validate()``.
"""

from __future__ import annotations

import os
from typing import Any

# ---------------------------------------------------------------------------
# Try the real jsonschema first; fall back to our stdlib implementation.
# ---------------------------------------------------------------------------

_USE_JSONSCHEMA = os.environ.get("MULTIAGENT_USE_JSONSCHEMA", "0") == "1"

try:
    import jsonschema as _jsonschema  # type: ignore[import]
    _HAS_JSONSCHEMA = True
except ModuleNotFoundError:
    _HAS_JSONSCHEMA = False


class _ValidationError(Exception):
    """Internal validation error (re-exported as ValidationError in contracts.py)."""


def _check_type(value: Any, expected: str, path: str) -> None:
    """Raise if *value* does not match the JSON Schema *expected* type."""
    type_map: dict[str, type | tuple[type, ...]] = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
        "null": type(None),
    }
    if expected not in type_map:
        return  # unknown type — skip
    # JSON Schema: booleans are NOT integers even though bool subclasses int.
    if expected == "integer" and isinstance(value, bool):
        raise _ValidationError(f"{path}: expected integer, got boolean")
    if expected == "number" and isinstance(value, bool):
        raise _ValidationError(f"{path}: expected number, got boolean")
    expected_py = type_map[expected]
    if not isinstance(value, expected_py):
        actual = type(value).__name__
        raise _ValidationError(
            f"{path}: expected type '{expected}', got '{actual}' ({value!r})"
        )


def _validate_node(schema: dict[str, Any], data: Any, path: str) -> None:
    """Recursively validate *data* against a JSON Schema *schema* node."""
    # ── type ──────────────────────────────────────────────────────────────
    if "type" in schema:
        _check_type(data, schema["type"], path)

    # ── required ──────────────────────────────────────────────────────────
    if "required" in schema and isinstance(data, dict):
        for key in schema["required"]:
            if key not in data:
                raise _ValidationError(f"{path}: missing required property '{key}'")

    # ── properties ────────────────────────────────────────────────────────
    if "properties" in schema and isinstance(data, dict):
        for prop_name, prop_schema in schema["properties"].items():
            if prop_name in data:
                _validate_node(prop_schema, data[prop_name], f"{path}.{prop_name}")

    # ── additionalProperties ──────────────────────────────────────────────
    if (
        schema.get("additionalProperties") is False
        and isinstance(data, dict)
        and "properties" in schema
    ):
        extra = set(data.keys()) - set(schema["properties"].keys())
        if extra:
            raise _ValidationError(
                f"{path}: additional properties not allowed: {sorted(extra)}"
            )

    # ── string constraints ────────────────────────────────────────────────
    if isinstance(data, str):
        if "minLength" in schema and len(data) < schema["minLength"]:
            raise _ValidationError(
                f"{path}: string length {len(data)} < minLength {schema['minLength']}"
            )
        if "maxLength" in schema and len(data) > schema["maxLength"]:
            raise _ValidationError(
                f"{path}: string length {len(data)} > maxLength {schema['maxLength']}"
            )

    # ── numeric constraints ───────────────────────────────────────────────
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if "minimum" in schema and data < schema["minimum"]:
            raise _ValidationError(
                f"{path}: {data} < minimum {schema['minimum']}"
            )
        if "maximum" in schema and data > schema["maximum"]:
            raise _ValidationError(
                f"{path}: {data} > maximum {schema['maximum']}"
            )

    # ── array items ───────────────────────────────────────────────────────
    if "items" in schema and isinstance(data, list):
        for i, item in enumerate(data):
            _validate_node(schema["items"], item, f"{path}[{i}]")


def validate_schema(schema_dict: dict[str, Any], data: Any) -> None:
    """Validate *data* against *schema_dict*.

    Uses the full ``jsonschema`` library when available (set
    ``MULTIAGENT_USE_JSONSCHEMA=1`` and install the optional extra), otherwise
    falls back to our lightweight stdlib implementation.

    Args:
        schema_dict: A plain JSON Schema dict (from ``ToolSchema.as_json_schema()``).
        data: The value to validate.

    Raises:
        _ValidationError: On the first schema violation.
    """
    if _USE_JSONSCHEMA and _HAS_JSONSCHEMA:
        try:
            _jsonschema.validate(instance=data, schema=schema_dict)
        except _jsonschema.ValidationError as exc:
            raise _ValidationError(exc.message) from exc
        return

    _validate_node(schema_dict, data, "$")
