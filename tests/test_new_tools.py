"""
Tests for new MCP tools: structure_filters in query_subgraph,
export_session, and construct_knowledge (LLM call mocked).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cks.core import (
    CanonicalRelation,
    KnowledgeObject,
    KnowledgeStructure,
    ObjectIdentity,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _obj(oid: str, otype: str = "Concept", name: str = "", **structure) -> KnowledgeObject:
    return KnowledgeObject(
        identity=ObjectIdentity(id=oid, type=otype, name=name or oid),
        structure=dict(structure),
    )


def _rel(oid: str, participants: list[str], relation_type: str = "links") -> CanonicalRelation:
    return CanonicalRelation(
        identity=ObjectIdentity(id=oid, type="Relation", name=oid),
        participants=participants,
        relation_type=relation_type,
    )


# ---------------------------------------------------------------------------
# query_subgraph _apply_structure_filter
# ---------------------------------------------------------------------------


@dataclass
class FakeSubgraphResult:
    structure: KnowledgeStructure
    total_found_nodes: int
    returned_nodes: int
    is_truncated: bool
    truncation_reason: str | None = None
    suggested_next_seed: str | None = None


def _fake_result(*objects) -> FakeSubgraphResult:
    ks = KnowledgeStructure(list(objects))
    non_rel = [o for o in ks.objects if not isinstance(o, CanonicalRelation)]
    return FakeSubgraphResult(
        structure=ks,
        total_found_nodes=len(non_rel),
        returned_nodes=len(non_rel),
        is_truncated=False,
    )


class TestStructureFilters:
    from cks_mcp.tools.query_subgraph import _apply_structure_filter

    def setup_method(self):
        from cks_mcp.tools.query_subgraph import _apply_structure_filter
        self._filter = _apply_structure_filter

    def test_filter_keeps_matching_objects(self):
        a = _obj("a", status="active")
        b = _obj("b", status="inactive")
        c = _obj("c", status="active")  # seed
        result = self._filter(_fake_result(a, b, c), ["c"], {"status": "active"})
        ids = {o.identity.id for o in result.structure.objects}
        assert "a" in ids
        assert "b" not in ids
        assert "c" in ids

    def test_seed_always_survives_filter(self):
        seed = _obj("seed", status="inactive")
        other = _obj("other", status="active")
        result = self._filter(_fake_result(seed, other), ["seed"], {"status": "active"})
        ids = {o.identity.id for o in result.structure.objects}
        assert "seed" in ids

    def test_relation_kept_when_both_participants_survive(self):
        a = _obj("a", domain="bio")
        b = _obj("b", domain="bio")
        r = _rel("r", ["a", "b"])
        result = self._filter(_fake_result(a, b, r), ["a"], {"domain": "bio"})
        ids = {o.identity.id for o in result.structure.objects}
        assert "r" in ids

    def test_relation_dropped_when_participant_filtered(self):
        a = _obj("a", domain="bio")
        b = _obj("b", domain="chem")  # will be filtered
        r = _rel("r", ["a", "b"])
        result = self._filter(_fake_result(a, b, r), ["a"], {"domain": "bio"})
        ids = {o.identity.id for o in result.structure.objects}
        assert "r" not in ids

    def test_multi_field_and_logic(self):
        a = _obj("a", status="active", domain="bio")
        b = _obj("b", status="active", domain="chem")
        c = _obj("c", status="inactive", domain="bio")
        seed = _obj("s", status="active", domain="bio")
        result = self._filter(
            _fake_result(a, b, c, seed),
            ["s"],
            {"status": "active", "domain": "bio"},
        )
        ids = {o.identity.id for o in result.structure.objects}
        assert "a" in ids   # both match
        assert "b" not in ids  # domain mismatch
        assert "c" not in ids  # status mismatch
        assert "s" in ids   # seed

    def test_empty_filters_keeps_all(self):
        a = _obj("a", status="active")
        b = _obj("b", status="inactive")
        result = self._filter(_fake_result(a, b), ["a"], {})
        ids = {o.identity.id for o in result.structure.objects}
        assert "a" in ids
        assert "b" in ids

    def test_returned_nodes_count_updated(self):
        a = _obj("a", status="active")
        b = _obj("b", status="inactive")
        c = _obj("c", status="active")
        result = self._filter(_fake_result(a, b, c), ["c"], {"status": "active"})
        assert result.returned_nodes == 2  # a and c

    def test_is_truncated_set_when_filtered(self):
        a = _obj("a", status="active")
        b = _obj("b", status="inactive")
        result = self._filter(_fake_result(a, b), ["a"], {"status": "active"})
        # total_found_nodes=2, returned_nodes=1 → truncated
        assert result.is_truncated is True

    def test_numeric_field_comparison(self):
        high = _obj("high", score=90)
        low = _obj("low", score=40)
        seed = _obj("seed", score=90)
        result = self._filter(_fake_result(high, low, seed), ["seed"], {"score": 90})
        ids = {o.identity.id for o in result.structure.objects}
        assert "high" in ids
        assert "low" not in ids

    def test_boolean_field_comparison(self):
        active = _obj("active", enabled=True)
        inactive = _obj("inactive", enabled=False)
        seed = _obj("seed", enabled=True)
        result = self._filter(
            _fake_result(active, inactive, seed), ["seed"], {"enabled": True}
        )
        ids = {o.identity.id for o in result.structure.objects}
        assert "active" in ids
        assert "inactive" not in ids


# ---------------------------------------------------------------------------
# export_session
# ---------------------------------------------------------------------------


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
        from cks_mcp.tools.export_session import export_session

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
        from cks_mcp.tools.export_session import export_session

        session = _make_mock_session("sess-1")
        runtime = _make_mock_runtime(session)

        result = await export_session(runtime, {"session_id": "sess-1", "format": "cks"})

        assert result["format"] == "cks"
        assert "cks_json" in result
        parsed = json.loads(result["cks_json"])
        assert "objects" in parsed

    @pytest.mark.asyncio
    async def test_export_missing_session_id(self):
        from cks_mcp.tools.export_session import export_session

        runtime = _make_mock_runtime(None)
        result = await export_session(runtime, {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_export_session_not_found(self):
        from cks_mcp.tools.export_session import export_session

        runtime = _make_mock_runtime(None)
        result = await export_session(runtime, {"session_id": "ghost"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_export_bundle_json_is_valid_json(self):
        from cks_mcp.tools.export_session import export_session

        session = _make_mock_session("sess-2")
        runtime = _make_mock_runtime(session)
        result = await export_session(runtime, {"session_id": "sess-2"})

        parsed = json.loads(result["bundle_json"])
        assert parsed["cks_mcp_export"] is True

    @pytest.mark.asyncio
    async def test_export_unknown_format(self):
        from cks_mcp.tools.export_session import export_session

        session = _make_mock_session("sess-1")
        runtime = _make_mock_runtime(session)
        result = await export_session(runtime, {"session_id": "sess-1", "format": "xml"})
        assert result.get("error") == "unsupported_format"

    @pytest.mark.asyncio
    async def test_export_bundle_include_structures(self):
        from cks_mcp.tools.export_session import export_session

        session = _make_mock_session("sess-1")
        runtime = _make_mock_runtime(session)
        result = await export_session(
            runtime, {"session_id": "sess-1", "include_structures": True}
        )
        versions = result["bundle"]["version_history"]["versions"]
        assert "cks_json" in versions[0]

    @pytest.mark.asyncio
    async def test_export_bundle_omits_structures_by_default(self):
        from cks_mcp.tools.export_session import export_session

        session = _make_mock_session("sess-1")
        runtime = _make_mock_runtime(session)
        result = await export_session(runtime, {"session_id": "sess-1"})
        versions = result["bundle"]["version_history"]["versions"]
        assert "cks_json" not in versions[0]

    @pytest.mark.asyncio
    async def test_export_schema_version_present(self):
        from cks_mcp.tools.export_session import _BUNDLE_SCHEMA_VERSION, export_session

        session = _make_mock_session("sess-1")
        runtime = _make_mock_runtime(session)
        result = await export_session(runtime, {"session_id": "sess-1"})
        assert result["bundle"]["schema_version"] == _BUNDLE_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# construct_knowledge (LLM mocked)
# ---------------------------------------------------------------------------

_VALID_CKS_JSON = json.dumps({
    "objects": [
        {
            "identity": {"id": "obj-sun", "type": "Concept", "name": "Sun"},
            "structure": {"description": "Star at the centre"},
        },
        {
            "identity": {"id": "obj-earth", "type": "Concept", "name": "Earth"},
            "structure": {"description": "Third planet"},
        },
        {
            "identity": {"id": "rel-orbits", "type": "Relation", "name": "Earth orbits Sun"},
            "structure": {
                "participants": ["obj-earth", "obj-sun"],
                "relation_type": "orbits",
            },
        },
    ]
})


def _make_construct_runtime() -> MagicMock:
    session = MagicMock()
    session.session_id = "sess-new"
    session.knowledge_structure = MagicMock()

    version = MagicMock()
    version.version_id = "ver-initial"

    runtime = MagicMock()
    runtime.create_session = AsyncMock(return_value=session)
    runtime.begin_transaction = MagicMock(return_value=MagicMock())
    runtime.commit_transaction = AsyncMock(return_value=version)
    runtime.core_bridge.serialize.return_value = _VALID_CKS_JSON
    return runtime


class TestConstructKnowledge:
    @pytest.mark.asyncio
    async def test_construct_success(self):
        from cks_mcp.tools.construct_knowledge import construct_knowledge

        runtime = _make_construct_runtime()
        with patch(
            "cks_mcp.tools.construct_knowledge._call_anthropic",
            return_value=_VALID_CKS_JSON,
        ):
            result = await construct_knowledge(
                runtime, {"text": "The Earth orbits the Sun."}
            )

        assert result.get("constructed") is True
        assert result["session_id"] == "sess-new"
        assert result["version_id"] == "ver-initial"
        assert result["objects_count"] == 2  # non-relation objects
        assert result["relations_count"] == 1

    @pytest.mark.asyncio
    async def test_construct_missing_text(self):
        from cks_mcp.tools.construct_knowledge import construct_knowledge

        runtime = _make_construct_runtime()
        result = await construct_knowledge(runtime, {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_construct_llm_failure(self):
        from cks_mcp.tools.construct_knowledge import construct_knowledge

        runtime = _make_construct_runtime()
        with patch(
            "cks_mcp.tools.construct_knowledge._call_anthropic",
            side_effect=RuntimeError("network error"),
        ):
            result = await construct_knowledge(runtime, {"text": "Some text"})

        assert result.get("error") == "llm_output_parse_error" or "LLM" in result.get("message", "") or result.get("error") == "llm_call_failed" or "error" in result

    @pytest.mark.asyncio
    async def test_construct_invalid_json_from_llm(self):
        from cks_mcp.tools.construct_knowledge import construct_knowledge

        runtime = _make_construct_runtime()
        with patch(
            "cks_mcp.tools.construct_knowledge._call_anthropic",
            return_value="This is not JSON at all!",
        ):
            result = await construct_knowledge(runtime, {"text": "Some text"})

        assert "error" in result

    @pytest.mark.asyncio
    async def test_construct_invalid_cks_from_llm(self):
        from cks_mcp.tools.construct_knowledge import construct_knowledge

        bad_json = json.dumps({
            "objects": [
                {
                    # Missing required "identity" key — will fail cks.parse
                    "structure": {"dangling": True}
                }
            ]
        })
        runtime = _make_construct_runtime()
        with patch(
            "cks_mcp.tools.construct_knowledge._call_anthropic",
            return_value=bad_json,
        ):
            result = await construct_knowledge(runtime, {"text": "Bad structure"})

        # Should return a parse/validation error, NOT raise
        assert "error" in result

    @pytest.mark.asyncio
    async def test_construct_with_hint(self):
        from cks_mcp.tools.construct_knowledge import construct_knowledge

        runtime = _make_construct_runtime()
        captured = {}

        def fake_call(prompt, model, max_tokens):
            captured["prompt"] = prompt
            return _VALID_CKS_JSON

        with patch("cks_mcp.tools.construct_knowledge._call_anthropic", side_effect=fake_call):
            await construct_knowledge(
                runtime, {"text": "Some text", "hint": "focus on orbital mechanics"}
            )

        assert "orbital mechanics" in captured["prompt"]

    @pytest.mark.asyncio
    async def test_construct_model_override(self):
        from cks_mcp.tools.construct_knowledge import construct_knowledge

        runtime = _make_construct_runtime()
        captured = {}

        def fake_call(prompt, model, max_tokens):
            captured["model"] = model
            return _VALID_CKS_JSON

        with patch("cks_mcp.tools.construct_knowledge._call_anthropic", side_effect=fake_call):
            await construct_knowledge(
                runtime, {"text": "x", "model": "claude-opus-4-6"}
            )

        assert captured["model"] == "claude-opus-4-6"

    @pytest.mark.asyncio
    async def test_construct_json_wrapped_in_markdown_fence(self):
        from cks_mcp.tools.construct_knowledge import construct_knowledge

        runtime = _make_construct_runtime()
        # LLM sometimes wraps output in ```json ... ```
        fenced = f"```json\n{_VALID_CKS_JSON}\n```"
        with patch(
            "cks_mcp.tools.construct_knowledge._call_anthropic",
            return_value=fenced,
        ):
            result = await construct_knowledge(runtime, {"text": "Earth orbits Sun"})

        assert result.get("constructed") is True

    @pytest.mark.asyncio
    async def test_construct_result_includes_model_used(self):
        from cks_mcp.tools.construct_knowledge import construct_knowledge

        runtime = _make_construct_runtime()
        with patch(
            "cks_mcp.tools.construct_knowledge._call_anthropic",
            return_value=_VALID_CKS_JSON,
        ):
            result = await construct_knowledge(runtime, {"text": "test"})

        assert "model_used" in result
