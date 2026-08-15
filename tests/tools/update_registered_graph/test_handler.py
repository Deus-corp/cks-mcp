"""Unit tests for the update_registered_graph MCP tool."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.tools.update_registered_graph.handler import update_registered_graph

pytestmark = pytest.mark.asyncio

_MODULE = "cks_mcp.tools.update_registered_graph.handler"


def _make_component_object(component_id: str, name: str, version: str):
    identity = MagicMock()
    identity.type = "Component"
    identity.id = component_id
    identity.name = name
    obj = MagicMock()
    obj.identity = identity
    obj.structure = {"version": version}
    return obj


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.get_graph = AsyncMock(
        return_value={
            "session_id": "s1",
            "description": "desc",
            "tags": "t1,t2",
            "public": False,
        }
    )
    session = MagicMock()
    session.knowledge_structure.objects = [
        _make_component_object("comp-cks-core", "cks-core", "1.0.0"),
    ]
    runtime.get_session = MagicMock(return_value=session)
    return runtime


async def test_missing_name(mock_runtime):
    result = await update_registered_graph(mock_runtime, {})
    assert result.get("error") == "missing_parameter"


async def test_graph_not_found(mock_runtime, monkeypatch):
    monkeypatch.setattr(
        f"{_MODULE}.check_component_versions",
        AsyncMock(return_value={"found": False}),
    )
    result = await update_registered_graph(mock_runtime, {"name": "missing-graph"})
    assert result == {"found": False}


async def test_propagates_check_error(mock_runtime, monkeypatch):
    monkeypatch.setattr(
        f"{_MODULE}.check_component_versions",
        AsyncMock(
            return_value={
                "found": True,
                "error": "session_not_available",
                "message": "not loaded",
            }
        ),
    )
    result = await update_registered_graph(mock_runtime, {"name": "g1"})
    assert result["error"] == "session_not_available"


async def test_already_current(mock_runtime, monkeypatch):
    monkeypatch.setattr(
        f"{_MODULE}.check_component_versions",
        AsyncMock(
            return_value={
                "found": True,
                "components": [
                    {
                        "component": "cks-core",
                        "graph_version": "1.0.0",
                        "actual_version": "1.0.0",
                        "status": "up_to_date",
                    }
                ],
            }
        ),
    )
    result = await update_registered_graph(mock_runtime, {"name": "g1"})
    assert result == {"updated": False, "reason": "already current"}


async def test_no_llm_provider_leaves_graph_untouched(mock_runtime, monkeypatch):
    monkeypatch.setattr(
        f"{_MODULE}.check_component_versions",
        AsyncMock(
            return_value={
                "found": True,
                "components": [
                    {
                        "component": "cks-core",
                        "graph_version": "1.0.0",
                        "actual_version": "1.1.0",
                        "status": "outdated",
                    }
                ],
            }
        ),
    )
    monkeypatch.setattr(
        f"{_MODULE}.construct_knowledge",
        AsyncMock(
            return_value={
                "error": "internal_error",
                "message": "Internal error: LLM call failed: No LLM provider available for construct_knowledge. Options: ...",
            }
        ),
    )
    evolve_mock = AsyncMock()
    register_mock = AsyncMock()
    monkeypatch.setattr(f"{_MODULE}.evolve_knowledge", evolve_mock)
    monkeypatch.setattr(f"{_MODULE}.register_graph", register_mock)

    result = await update_registered_graph(mock_runtime, {"name": "g1"})

    assert result == {"error": "LLM provider required"}
    evolve_mock.assert_not_called()
    register_mock.assert_not_called()


async def test_construct_knowledge_other_error_propagates(mock_runtime, monkeypatch):
    monkeypatch.setattr(
        f"{_MODULE}.check_component_versions",
        AsyncMock(
            return_value={
                "found": True,
                "components": [
                    {
                        "component": "cks-core",
                        "graph_version": "1.0.0",
                        "actual_version": "1.1.0",
                        "status": "outdated",
                    }
                ],
            }
        ),
    )
    monkeypatch.setattr(
        f"{_MODULE}.construct_knowledge",
        AsyncMock(return_value={"error": "validation_failed", "message": "bad"}),
    )
    result = await update_registered_graph(mock_runtime, {"name": "g1"})
    assert result["error"] == "construct_knowledge_failed"
    assert result["component"] == "cks-core"


async def test_successful_update(mock_runtime, monkeypatch):
    monkeypatch.setattr(
        f"{_MODULE}.check_component_versions",
        AsyncMock(
            return_value={
                "found": True,
                "components": [
                    {
                        "component": "cks-core",
                        "graph_version": "1.0.0",
                        "actual_version": "1.1.0",
                        "status": "outdated",
                    }
                ],
            }
        ),
    )
    serialized = json.dumps(
        {
            "objects": [
                {
                    "identity": {
                        "id": "obj-release",
                        "type": "Release",
                        "name": "cks-core 1.1.0",
                    },
                    "structure": {"summary": "New release"},
                },
                {
                    "identity": {
                        "id": "rel-release-of",
                        "type": "Relation",
                        "name": "is release of",
                    },
                    "structure": {
                        "participants": ["obj-release", "comp-cks-core"],
                        "relation_type": "release_of",
                    },
                },
            ]
        }
    )
    monkeypatch.setattr(
        f"{_MODULE}.construct_knowledge",
        AsyncMock(return_value={"constructed": True, "serialized": serialized}),
    )
    evolve_mock = AsyncMock(return_value={"evolved": True, "session_id": "s2"})
    monkeypatch.setattr(f"{_MODULE}.evolve_knowledge", evolve_mock)
    register_mock = AsyncMock(return_value={"registered": True, "name": "g1", "public": False})
    monkeypatch.setattr(f"{_MODULE}.register_graph", register_mock)

    result = await update_registered_graph(mock_runtime, {"name": "g1"})

    assert result == {"updated": True, "components_updated": ["cks-core"]}

    evolve_args = evolve_mock.await_args.args[1]
    assert evolve_args["session_id"] == "s1"
    ops = evolve_args["operations"]
    op_types = [op["type"] for op in ops]
    assert "add_object" in op_types
    assert "add_relation" in op_types
    update_ops = [op for op in ops if op["type"] == "update_object"]
    assert update_ops == [
        {
            "type": "update_object",
            "object_id": "comp-cks-core",
            "structure_patch": {"version": "1.1.0"},
        }
    ]

    register_mock.assert_awaited_once_with(
        mock_runtime,
        {
            "name": "g1",
            "session_id": "s2",
            "description": "desc",
            "tags": "t1,t2",
            "public": False,
            "visibility": None,
            "team": None,
        },
    )


async def test_evolve_failure_propagates(mock_runtime, monkeypatch):
    monkeypatch.setattr(
        f"{_MODULE}.check_component_versions",
        AsyncMock(
            return_value={
                "found": True,
                "components": [
                    {
                        "component": "cks-core",
                        "graph_version": "1.0.0",
                        "actual_version": "1.1.0",
                        "status": "outdated",
                    }
                ],
            }
        ),
    )
    monkeypatch.setattr(
        f"{_MODULE}.construct_knowledge",
        AsyncMock(
            return_value={
                "constructed": True,
                "serialized": json.dumps({"objects": []}),
            }
        ),
    )
    monkeypatch.setattr(
        f"{_MODULE}.evolve_knowledge",
        AsyncMock(return_value={"error": "Evolution failed: boom"}),
    )
    register_mock = AsyncMock()
    monkeypatch.setattr(f"{_MODULE}.register_graph", register_mock)

    result = await update_registered_graph(mock_runtime, {"name": "g1"})

    assert result["error"] == "evolve_failed"
    register_mock.assert_not_called()