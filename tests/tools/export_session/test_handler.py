"""Unit tests for the export_session MCP tool."""

from __future__ import annotations

import json
from datetime import UTC
from unittest.mock import MagicMock

import pytest
from cks.core import (
    KnowledgeObject,
    KnowledgeStructure,
    ObjectIdentity,
)


def _obj(oid: str, otype: str = "Concept", name: str = "", **structure) -> KnowledgeObject:
    return KnowledgeObject(
        identity=ObjectIdentity(id=oid, type=otype, name=name or oid),
        structure=dict(structure),
    )


def _make_mock_session(session_id: str, n_objects: int = 2) -> MagicMock:
    """Build a minimal mock session compatible with export_session."""
    objects = [
        _obj(f"obj-{i}", name=f"Object {i}", val=i) for i in range(n_objects)
    ]
    ks = KnowledgeStructure(objects)

    from datetime import datetime

    version = MagicMock()
    version.version_id = "ver-001"
    version.transaction_id = "tx-001"
    version.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    version.state_hash = "abc123"
    version.knowledge_structure = ks

    session = MagicMock()
    session.session_id = session_id
    session.parent_session_id = None
    session.parent_version_id = None
    session.closed = False
    session.metadata = {}
    session.knowledge_structure = ks
    session.version_history = [version]
    return session


def _make_mock_runtime(session: MagicMock | None = None) -> MagicMock:

    runtime = MagicMock()
    runtime.get_session.return_value = session
    runtime.core_bridge.serialize.side_effect = lambda ks: json.dumps(
        {"objects": [{"identity": {"id": o.identity.id, "type": o.identity.type, "name": o.identity.name}, "structure": dict(o.structure)} for o in ks.objects]}
    )
    return runtime


class TestExportSession:
    @pytest.mark.asyncio
    async def test_export_bundle_format(self):
        from cks_mcp.tools.export_session.handler import export_session

        session = _make_mock_session("sess-1")
        runtime = _make_mock_runtime(session)

        result = await export_session(runtime, {"session_id": "sess-1"})

        assert result["format"] == "bundle"
        assert result["session_id"] == "sess-1"
        bundle = result["bundle"]
        assert bundle["cks_mcp_export"] is True
        assert bundle["session"]["session_id"] == "sess-1"
        assert bundle["current_structure"]["objects_count"] == 2
        assert bundle["version_history"]["count"] == 1

    @pytest.mark.asyncio
    async def test_export_cks_format(self):
        from cks_mcp.tools.export_session.handler import export_session

        session = _make_mock_session("sess-1")
        runtime = _make_mock_runtime(session)

        result = await export_session(runtime, {"session_id": "sess-1", "format": "cks"})

        assert result["format"] == "cks"
        assert "cks_json" in result
        parsed = json.loads(result["cks_json"])
        assert "objects" in parsed

    @pytest.mark.asyncio
    async def test_export_missing_session_id(self):
        from cks_mcp.tools.export_session.handler import export_session

        runtime = _make_mock_runtime(None)
        result = await export_session(runtime, {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_export_session_not_found(self):
        from cks_mcp.tools.export_session.handler import export_session

        runtime = _make_mock_runtime(None)
        result = await export_session(runtime, {"session_id": "ghost"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_export_bundle_json_is_valid_json(self):
        from cks_mcp.tools.export_session.handler import export_session

        session = _make_mock_session("sess-2")
        runtime = _make_mock_runtime(session)
        result = await export_session(runtime, {"session_id": "sess-2"})

        parsed = json.loads(result["bundle_json"])
        assert parsed["cks_mcp_export"] is True

    @pytest.mark.asyncio
    async def test_export_unknown_format(self):
        from cks_mcp.tools.export_session.handler import export_session

        session = _make_mock_session("sess-1")
        runtime = _make_mock_runtime(session)
        result = await export_session(runtime, {"session_id": "sess-1", "format": "xml"})
        assert result.get("error") == "unsupported_format"

    @pytest.mark.asyncio
    async def test_export_bundle_include_structures(self):
        from cks_mcp.tools.export_session.handler import export_session

        session = _make_mock_session("sess-1")
        runtime = _make_mock_runtime(session)
        result = await export_session(
            runtime, {"session_id": "sess-1", "include_structures": True}
        )
        versions = result["bundle"]["version_history"]["versions"]
        assert "cks_json" in versions[0]

    @pytest.mark.asyncio
    async def test_export_bundle_omits_structures_by_default(self):
        from cks_mcp.tools.export_session.handler import export_session

        session = _make_mock_session("sess-1")
        runtime = _make_mock_runtime(session)
        result = await export_session(runtime, {"session_id": "sess-1"})
        versions = result["bundle"]["version_history"]["versions"]
        assert "cks_json" not in versions[0]

    @pytest.mark.asyncio
    async def test_export_schema_version_present(self):
        from cks_mcp.tools.export_session.handler import (
            _BUNDLE_SCHEMA_VERSION,
            export_session,
        )

        session = _make_mock_session("sess-1")
        runtime = _make_mock_runtime(session)
        result = await export_session(runtime, {"session_id": "sess-1"})
        assert result["bundle"]["schema_version"] == _BUNDLE_SCHEMA_VERSION
