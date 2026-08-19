"""Regression tests for Gemini-specific tool-schema normalization
(cks-mcp).

Google Gemini's function-calling schema subset rejects several
keywords that are perfectly valid JSON Schema and that our source
tool schemas legitimately use (most notably ``additionalProperties:
false`` on zero-argument tools). ``_normalize_schema_for_google`` is
the provider-specific fix: it strips/rewrites those keywords on the
way out to Google only, without touching the source schemas that
every other provider (and MCP clients generally) rely on.

These tests guard three things:
  1. The Google-bound payload never contains an unsupported keyword,
     for every tool currently registered.
  2. The *source* schemas are untouched -- in particular that
     ``additionalProperties: false`` is still present where we
     intentionally added it, proving the fix is normalization-on-the-
     way-out, not a source-schema edit.
  3. A basic "would Gemini accept this field name" validator passes
     for every normalized schema.
"""

from __future__ import annotations

from typing import Any

from cks_mcp.llm.providers import google as _google
from cks_mcp.registry import TOOLS

# Keywords Gemini's function-declaration schema subset does not
# recognize. Mirrors _GOOGLE_UNSUPPORTED_KEYWORDS in google.py, but
# kept as an independent literal here so this test still catches a
# regression if that set in the source module were accidentally
# narrowed.
_UNSUPPORTED_KEYWORDS = {
    "additionalProperties",
    "$schema",
    "$ref",
    "anyOf",
    "oneOf",
    "allOf",
    "default",
    "examples",
    "const",
    "readOnly",
    "writeOnly",
    "deprecated",
}

# The only field names a Gemini-normalized schema node is allowed to
# carry (plus nothing outside this set -- see _assert_gemini_compatible
# below, which is stricter than merely "no unsupported keyword" and
# also catches unrelated stray keys).
_GEMINI_ALLOWED_KEYWORDS = {
    "type",
    "description",
    "enum",
    "properties",
    "items",
    "required",
    "nullable",
}


def _iter_nodes(node: Any):
    """Yield every dict *schema* node reachable from ``node`` (including
    itself). Schema nodes are the dicts whose keys are JSON-Schema
    keywords (``type``, ``properties``, ``items``, ...) -- as opposed
    to e.g. the dict *under* ``properties``, whose keys are arbitrary
    parameter names, or the dict under ``items``/a ``properties``
    entry, which is itself a schema node and handled by the recursive
    calls below.
    """
    if isinstance(node, dict):
        yield node
        if "properties" in node and isinstance(node["properties"], dict):
            for prop_schema in node["properties"].values():
                yield from _iter_nodes(prop_schema)
        if "items" in node:
            yield from _iter_nodes(node["items"])
    elif isinstance(node, list):
        for value in node:
            yield from _iter_nodes(value)


def _assert_gemini_compatible(schema: Any, *, tool_name: str) -> None:
    """Minimal stand-in for Gemini's schema validator: rejects any
    schema node containing a key outside the field names Gemini's
    function-calling schema subset understands.
    """
    for node in _iter_nodes(schema):
        unknown = set(node.keys()) - _GEMINI_ALLOWED_KEYWORDS
        assert not unknown, (
            f"{tool_name}: Gemini-normalized schema has unsupported "
            f"field(s) {sorted(unknown)} in node {node!r}"
        )


def _all_tool_input_schemas() -> dict[str, dict]:
    schemas = {}
    for name, tool in TOOLS.items():
        schema = tool.get("inputSchema")
        assert schema is not None, f"{name}: missing inputSchema"
        schemas[name] = schema
    assert schemas, "registry.TOOLS is empty -- test isn't exercising anything"
    return schemas


# ---------------------------------------------------------------------------
# 1. No unsupported keyword reaches the Google-bound payload.
# ---------------------------------------------------------------------------


def test_normalize_strips_additional_properties():
    schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    result = _google._normalize_schema_for_google(schema)
    assert "additionalProperties" not in result


def test_normalize_strips_all_unsupported_keywords_nested():
    schema = {
        "type": "object",
        "$schema": "http://json-schema.org/draft-07/schema#",
        "properties": {
            "session_id": {
                "type": "string",
                "default": "abc",
                "examples": ["abc", "def"],
                "deprecated": False,
            },
            "mode": {
                "const": "strict",
                "readOnly": True,
            },
            "ref_field": {"$ref": "#/definitions/Thing"},
            "items_list": {
                "type": "array",
                "items": {"type": "string", "writeOnly": True},
            },
        },
        "additionalProperties": False,
    }
    result = _google._normalize_schema_for_google(schema)

    for node in _iter_nodes(result):
        for keyword in _UNSUPPORTED_KEYWORDS:
            assert keyword not in node, f"{keyword} leaked into normalized schema: {node!r}"


def test_normalize_collapses_anyof_to_permissive_object():
    schema = {
        "type": "object",
        "properties": {
            "value": {
                "anyOf": [{"type": "string"}, {"type": "integer"}],
                "description": "A flexible value.",
            }
        },
    }
    result = _google._normalize_schema_for_google(schema)
    value_schema = result["properties"]["value"]
    assert "anyOf" not in value_schema
    assert "oneOf" not in value_schema
    assert "allOf" not in value_schema
    # description is preserved since Gemini does support it
    assert value_schema.get("description") == "A flexible value."


def test_normalize_collapses_oneof_and_allof_too():
    for keyword, member in (
        ("oneOf", [{"type": "string"}, {"type": "null"}]),
        ("allOf", [{"type": "object"}]),
    ):
        schema = {"type": "object", "properties": {"x": {keyword: member}}}
        result = _google._normalize_schema_for_google(schema)
        assert keyword not in result["properties"]["x"]


def test_normalize_keeps_supported_keywords():
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "A name.", "enum": ["a", "b"]},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name"],
    }
    result = _google._normalize_schema_for_google(schema)
    assert result["type"] == "object"
    assert result["required"] == ["name"]
    assert result["properties"]["name"]["type"] == "string"
    assert result["properties"]["name"]["description"] == "A name."
    assert result["properties"]["name"]["enum"] == ["a", "b"]
    assert result["properties"]["tags"]["items"]["type"] == "string"


def test_normalize_does_not_mutate_input():
    schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    original = {k: v for k, v in schema.items()}
    _google._normalize_schema_for_google(schema)
    assert schema == original, "normalization must not mutate the source schema in place"


def test_to_google_tools_payload_never_contains_additional_properties():
    tools = [
        {
            "name": name,
            "description": tool.get("description", ""),
            "input_schema": tool["inputSchema"],
        }
        for name, tool in TOOLS.items()
    ]
    google_tools = _google._to_google_tools(tools)
    for decl in google_tools[0]["functionDeclarations"]:
        for node in _iter_nodes(decl["parameters"]):
            for keyword in _UNSUPPORTED_KEYWORDS:
                assert keyword not in node, (
                    f"{decl['name']}: unsupported keyword {keyword!r} present "
                    "in Google-bound payload"
                )


# ---------------------------------------------------------------------------
# 2. Source schemas (registry.TOOLS / MCP inputSchema) are untouched.
# ---------------------------------------------------------------------------


def test_source_schemas_still_contain_additional_properties_false():
    """Sanity check that the fix is normalization-on-the-way-out, not a
    source-schema edit -- if this starts failing, someone removed
    ``additionalProperties: false`` from the tool schemas directly,
    which reopens the reason this normalization step exists.
    """
    schemas = _all_tool_input_schemas()
    found_any = False
    for schema in schemas.values():
        for node in _iter_nodes(schema):
            if node.get("additionalProperties") is False:
                found_any = True
                break
    assert found_any, (
        "expected at least one registered tool schema to still declare "
        "'additionalProperties: false' -- source schemas must remain unchanged"
    )


def test_normalize_for_google_leaves_registry_tools_schema_object_unchanged():
    """Calling the normalizer must never mutate the schema objects
    referenced from registry.TOOLS -- those are shared, long-lived
    objects also served verbatim over MCP.
    """
    for name, schema in _all_tool_input_schemas().items():
        import copy

        before = copy.deepcopy(schema)
        _google._normalize_schema_for_google(schema)
        assert schema == before, f"{name}: inputSchema was mutated by Google normalization"


# ---------------------------------------------------------------------------
# 3. Every registered tool's Google-normalized schema passes a basic
#    "would Gemini accept this" validator.
# ---------------------------------------------------------------------------


def test_every_registered_tool_schema_normalizes_to_gemini_compatible_shape():
    for name, schema in _all_tool_input_schemas().items():
        normalized = _google._normalize_schema_for_google(schema)
        _assert_gemini_compatible(normalized, tool_name=name)
