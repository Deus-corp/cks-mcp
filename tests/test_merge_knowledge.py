"""
Tests for merge_knowledge.
"""

import json

import pytest
from cks_runtime.runtime import Runtime
from cks_runtime_plugins.cks_core import CksCoreAdapter

from cks_mcp.tools.merge import merge_knowledge

pytestmark = pytest.mark.asyncio


def make_runtime() -> Runtime:
    return Runtime(core=CksCoreAdapter())


async def test_merge_knowledge_no_conflict():
    runtime = make_runtime()
    base = json.dumps({
        "objects": [
            {"identity": {"id": "shared", "type": "Thing", "name": "shared"}, "structure": {"note": "base"}}
        ]
    })
    branch_a = json.dumps({
        "objects": [
            {"identity": {"id": "shared", "type": "Thing", "name": "shared"}, "structure": {"note": "base"}},
            {"identity": {"id": "a", "type": "Thing", "name": "a"}, "structure": {}}
        ]
    })
    branch_b = json.dumps({
        "objects": [
            {"identity": {"id": "shared", "type": "Thing", "name": "shared"}, "structure": {"note": "base"}},
            {"identity": {"id": "b", "type": "Thing", "name": "b"}, "structure": {}}
        ]
    })
    result = await merge_knowledge(runtime, {
        "json_data_base": base,
        "json_data_branch_a": branch_a,
        "json_data_branch_b": branch_b,
    })
    assert result["merged"] is True
    assert "a" in result["serialized"]
    assert "b" in result["serialized"]


async def test_merge_knowledge_reports_conflict():
    runtime = make_runtime()
    base = json.dumps({
        "objects": [
            {"identity": {"id": "shared", "type": "Thing", "name": "shared"}, "structure": {"note": "base"}}
        ]
    })
    branch_a = json.dumps({
        "objects": [
            {"identity": {"id": "shared", "type": "Thing", "name": "shared"}, "structure": {"note": "edited by A"}}
        ]
    })
    branch_b = json.dumps({
        "objects": [
            {"identity": {"id": "shared", "type": "Thing", "name": "shared"}, "structure": {"note": "edited by B"}}
        ]
    })
    result = await merge_knowledge(runtime, {
        "json_data_base": base,
        "json_data_branch_a": branch_a,
        "json_data_branch_b": branch_b,
    })
    assert result["merged"] is False
    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0]["object_id"] == "shared"


async def test_merge_knowledge_resolutions_branch_a_and_branch_b():
    runtime = make_runtime()
    base = json.dumps({
        "objects": [
            {"identity": {"id": "shared", "type": "Thing", "name": "shared"}, "structure": {"note": "base"}}
        ]
    })
    branch_a = json.dumps({
        "objects": [
            {"identity": {"id": "shared", "type": "Thing", "name": "shared"}, "structure": {"note": "edited by A"}}
        ]
    })
    branch_b = json.dumps({
        "objects": [
            {"identity": {"id": "shared", "type": "Thing", "name": "shared"}, "structure": {"note": "edited by B"}}
        ]
    })
    result = await merge_knowledge(runtime, {
        "json_data_base": base,
        "json_data_branch_a": branch_a,
        "json_data_branch_b": branch_b,
        "resolutions": {"shared": "branch_a"},
    })
    assert result["merged"] is True
    assert "edited by A" in result["serialized"]

    result = await merge_knowledge(runtime, {
        "json_data_base": base,
        "json_data_branch_a": branch_a,
        "json_data_branch_b": branch_b,
        "resolutions": {"shared": "branch_b"},
    })
    assert result["merged"] is True
    assert "edited by B" in result["serialized"]


async def test_merge_knowledge_resolutions_custom_object():
    runtime = make_runtime()
    base = json.dumps({
        "objects": [
            {"identity": {"id": "shared", "type": "Thing", "name": "shared"}, "structure": {"note": "base"}}
        ]
    })
    branch_a = json.dumps({
        "objects": [
            {"identity": {"id": "shared", "type": "Thing", "name": "shared"}, "structure": {"note": "edited by A"}}
        ]
    })
    branch_b = json.dumps({
        "objects": [
            {"identity": {"id": "shared", "type": "Thing", "name": "shared"}, "structure": {"note": "edited by B"}}
        ]
    })
    result = await merge_knowledge(runtime, {
        "json_data_base": base,
        "json_data_branch_a": branch_a,
        "json_data_branch_b": branch_b,
        "resolutions": {
            "shared": {
                "identity": {"id": "shared", "type": "Thing", "name": "shared"},
                "structure": {"note": "synthesized"},
            }
        },
    })
    assert result["merged"] is True
    assert "synthesized" in result["serialized"]


async def test_merge_knowledge_resolutions_malformed_custom_object_reports_error():
    runtime = make_runtime()
    base = json.dumps({
        "objects": [
            {"identity": {"id": "shared", "type": "Thing", "name": "shared"}, "structure": {"note": "base"}}
        ]
    })
    branch_a = json.dumps({
        "objects": [
            {"identity": {"id": "shared", "type": "Thing", "name": "shared"}, "structure": {"note": "edited by A"}}
        ]
    })
    branch_b = json.dumps({
        "objects": [
            {"identity": {"id": "shared", "type": "Thing", "name": "shared"}, "structure": {"note": "edited by B"}}
        ]
    })
    result = await merge_knowledge(runtime, {
        "json_data_base": base,
        "json_data_branch_a": branch_a,
        "json_data_branch_b": branch_b,
        "resolutions": {"shared": {"structure": {"note": "no identity field"}}},
    })
    assert "error" in result


async def test_merge_knowledge_resolutions_partial_still_reports_remaining():
    runtime = make_runtime()
    base = json.dumps({
        "objects": [
            {"identity": {"id": "a", "type": "Thing", "name": "a"}, "structure": {"note": "base-a"}},
            {"identity": {"id": "b", "type": "Thing", "name": "b"}, "structure": {"note": "base-b"}},
        ]
    })
    branch_a = json.dumps({
        "objects": [
            {"identity": {"id": "a", "type": "Thing", "name": "a"}, "structure": {"note": "edited-a-A"}},
            {"identity": {"id": "b", "type": "Thing", "name": "b"}, "structure": {"note": "edited-b-A"}},
        ]
    })
    branch_b = json.dumps({
        "objects": [
            {"identity": {"id": "a", "type": "Thing", "name": "a"}, "structure": {"note": "edited-a-B"}},
            {"identity": {"id": "b", "type": "Thing", "name": "b"}, "structure": {"note": "edited-b-B"}},
        ]
    })
    result = await merge_knowledge(runtime, {
        "json_data_base": base,
        "json_data_branch_a": branch_a,
        "json_data_branch_b": branch_b,
        "resolutions": {"a": "branch_a"},
    })
    assert result["merged"] is False
    assert [c["object_id"] for c in result["conflicts"]] == ["b"]


async def test_merge_knowledge_invalid_json_reports_error():
    runtime = make_runtime()
    result = await merge_knowledge(runtime, {
        "json_data_base": "not json",
        "json_data_branch_a": "{}",
        "json_data_branch_b": "{}",
    })
    assert "error" in result