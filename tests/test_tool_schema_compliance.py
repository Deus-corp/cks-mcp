"""Strict JSON Schema compliance audit for every registered tool's
``inputSchema`` (cks-mcp).

Gemini's function-calling validator (and strict JSON Schema validators
generally) reject shapes that plain JSON Schema tolerates, e.g. an
``array`` with no ``items``, or an ``items``/``properties`` value with
no ``type``. ``google.py``'s ``_normalize_schema_for_google`` already
patches this up on the wire for the Google provider specifically, but
that's a runtime band-aid -- the tools' own declared schemas should be
correct at the source so every provider (and any strict external
consumer of the MCP tool list) benefits, not just Google.

This module doesn't repair anything itself; it's a regression guard
that walks ``registry.TOOLS`` and fails loudly if a schema regresses
into one of the known-bad shapes.
"""

from __future__ import annotations

import json
from typing import Any

from cks_mcp.registry import TOOLS

# Property shapes that legitimately have no "type" keyword and are not
# schema bugs: $ref/anyOf/oneOf/allOf compositions, and enum-only
# properties (which imply their type from the enum values).
_TYPE_EXEMPT_KEYS = {"$ref", "anyOf", "oneOf", "allOf", "enum", "const"}


def _iter_schema_nodes(node: Any, path: str):
    """Yield (path, node) for every dict node reachable from ``node``."""
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from _iter_schema_nodes(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _iter_schema_nodes(value, f"{path}[{i}]")


def _all_tool_schemas() -> dict[str, dict]:
    schemas = {}
    for name, tool in TOOLS.items():
        schema = tool.get("inputSchema")
        assert schema is not None, f"{name}: missing inputSchema"
        schemas[name] = schema
    assert schemas, "registry.TOOLS is empty -- test isn't exercising anything"
    return schemas


def test_every_tool_schema_serializes_to_valid_json():
    for name, schema in _all_tool_schemas().items():
        try:
            json.dumps(schema)
        except (TypeError, ValueError) as exc:  # pragma: no cover - failure path
            raise AssertionError(f"{name}: inputSchema is not JSON-serializable: {exc}")


def test_every_array_parameter_has_items_with_type():
    failures: list[str] = []
    for name, schema in _all_tool_schemas().items():
        for path, node in _iter_schema_nodes(schema, name):
            if node.get("type") != "array":
                continue
            items = node.get("items")
            if not isinstance(items, dict):
                failures.append(f"{path}: array has no 'items' object")
                continue
            has_type = "type" in items or bool(_TYPE_EXEMPT_KEYS & items.keys())
            if not has_type:
                failures.append(f"{path}: array 'items' has no 'type' (and no $ref/anyOf/oneOf/allOf/enum)")
    assert not failures, "Array schema gaps found:\n" + "\n".join(failures)


def test_every_simple_object_property_has_a_type():
    """Every entry under an object's 'properties' must declare 'type',
    unless it's a composition ($ref/anyOf/oneOf/allOf) or enum/const,
    which imply type without the keyword."""
    failures: list[str] = []
    for name, schema in _all_tool_schemas().items():
        for path, node in _iter_schema_nodes(schema, name):
            props = node.get("properties")
            if not isinstance(props, dict):
                continue
            for prop_name, prop_schema in props.items():
                if not isinstance(prop_schema, dict):
                    failures.append(f"{path}.properties.{prop_name}: not an object")
                    continue
                has_type = "type" in prop_schema or bool(
                    _TYPE_EXEMPT_KEYS & prop_schema.keys()
                )
                if not has_type:
                    failures.append(
                        f"{path}.properties.{prop_name}: property has no 'type' "
                        "(and no $ref/anyOf/oneOf/allOf/enum/const)"
                    )
    assert not failures, "Object property schema gaps found:\n" + "\n".join(failures)


def test_object_schemas_with_no_properties_declare_additional_properties():
    """A zero-argument tool's inputSchema should make the empty shape
    explicit (additionalProperties: false) rather than leaving an
    object type with an empty properties dict and no
    additionalProperties -- some strict validators treat that as
    under-specified ("object with unknown shape") rather than "object
    that accepts nothing"."""
    failures: list[str] = []
    for name, schema in _all_tool_schemas().items():
        for path, node in _iter_schema_nodes(schema, name):
            if node.get("type") != "object":
                continue
            if node.get("properties") == {} and "additionalProperties" not in node:
                failures.append(f"{path}: empty 'properties' with no 'additionalProperties'")
    assert not failures, "Under-specified empty-object schemas found:\n" + "\n".join(failures)


def test_no_schema_regresses_requiredness_to_missing_required_key_silently():
    """Not a correctness check on its own (schemas may legitimately
    omit 'required' when nothing is required), but guards that
    'required', where present, is always a list of strings -- a
    malformed 'required' is a common source of strict-validator
    rejections distinct from the array/property issues above."""
    failures: list[str] = []
    for name, schema in _all_tool_schemas().items():
        for path, node in _iter_schema_nodes(schema, name):
            if "required" not in node:
                continue
            required = node["required"]
            if not isinstance(required, list) or not all(
                isinstance(r, str) for r in required
            ):
                failures.append(f"{path}: 'required' is not a list[str]: {required!r}")
    assert not failures, "Malformed 'required' found:\n" + "\n".join(failures)
