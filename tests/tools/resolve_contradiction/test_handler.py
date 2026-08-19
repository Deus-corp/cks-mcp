"""Unit tests for the resolve_contradiction MCP tool."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


def _real_runtime():
    from cks_runtime.adapters.cks_core import CksCoreAdapter
    from cks_runtime.runtime import Runtime
    return Runtime(core=CksCoreAdapter())


_MUTUAL_EXCLUSION_JSON = (
    '{"objects": ['
    '{"identity": {"id": "rule-1", "type": "MutualExclusionRule", "name": "r"}, '
    '"structure": {"relation_type_a": "supports", "relation_type_b": "contradicts"}},'
    '{"identity": {"id": "a", "type": "Claim", "name": "A"}, "structure": {}},'
    '{"identity": {"id": "b", "type": "Claim", "name": "B"}, "structure": {}},'
    '{"identity": {"id": "rel-supports", "type": "Relation", "name": "r1"}, '
    '"structure": {"participants": ["a", "b"], "relation_type": "supports"}},'
    '{"identity": {"id": "rel-contradicts", "type": "Relation", "name": "r2"}, '
    '"structure": {"participants": ["a", "b"], "relation_type": "contradicts"}}'
    ']}'
)

_FUNCTIONAL_RELATION_JSON = (
    '{"objects": ['
    '{"identity": {"id": "rule-1", "type": "FunctionalRelationRule", "name": "r"}, '
    '"structure": {"relation_type": "orbits"}},'
    '{"identity": {"id": "earth", "type": "Planet", "name": "Earth"}, "structure": {}},'
    '{"identity": {"id": "sun", "type": "Star", "name": "Sun"}, "structure": {}},'
    '{"identity": {"id": "mars", "type": "Planet", "name": "Mars"}, "structure": {}},'
    '{"identity": {"id": "rel-orbits-mars", "type": "Relation", "name": "r1"}, '
    '"structure": {"participants": ["earth", "mars"], "relation_type": "orbits"}},'
    '{"identity": {"id": "rel-orbits-sun", "type": "Relation", "name": "r2"}, '
    '"structure": {"participants": ["earth", "sun"], "relation_type": "orbits"}}'
    ']}'
)


async def test_resolve_contradiction_session_not_found():
    from cks_mcp.tools.resolve_contradiction.handler import resolve_contradiction

    runtime = _real_runtime()
    result = await resolve_contradiction(runtime, {"session_id": "does-not-exist"})
    assert result["error"] == "session_not_found"


async def test_resolve_contradiction_missing_session_id():
    from cks_mcp.tools.resolve_contradiction.handler import resolve_contradiction

    runtime = _real_runtime()
    result = await resolve_contradiction(runtime, {})
    assert result["error"] == "missing_parameter"


async def test_resolve_contradiction_no_ids_lists_only():
    """Called with only session_id, this is read-only (like
    detect_contradictions) and applies no operations."""
    from cks import parse

    from cks_mcp.tools.resolve_contradiction.handler import resolve_contradiction

    runtime = _real_runtime()
    structure = parse(_MUTUAL_EXCLUSION_JSON)
    session = await runtime.create_session(structure)

    result = await resolve_contradiction(runtime, {"session_id": session.session_id})

    assert result["contradiction_count"] == 1
    contradiction = result["contradictions"][0]
    assert contradiction["code"] == "CKS-EXT-MUTUAL-EXCLUSION"
    assert contradiction["relation_ids"] == ["rel-contradicts", "rel-supports"]

    # No relation was removed -- structure is unchanged.
    relation_ids = {r.identity.id for r in session.knowledge_structure.relations()}
    assert {"rel-supports", "rel-contradicts"}.issubset(relation_ids)


async def test_resolve_contradiction_no_contradictions_is_empty():
    from cks import parse

    from cks_mcp.tools.resolve_contradiction.handler import resolve_contradiction

    runtime = _real_runtime()
    structure = parse(
        '{"objects":[{"identity":{"id":"obj-1","type":"Concept","name":"A"},"structure":{}}]}'
    )
    session = await runtime.create_session(structure)

    result = await resolve_contradiction(runtime, {"session_id": session.session_id})

    assert result["contradiction_count"] == 0
    assert result["contradictions"] == []


async def test_resolve_contradiction_mutual_exclusion_dry_run():
    """contradiction_ids given but commit not set -- operations are
    computed and returned, but not applied."""
    from cks import parse

    from cks_mcp.tools.resolve_contradiction.handler import resolve_contradiction

    runtime = _real_runtime()
    structure = parse(_MUTUAL_EXCLUSION_JSON)
    session = await runtime.create_session(structure)

    listing = await resolve_contradiction(runtime, {"session_id": session.session_id})
    contradiction_id = listing["contradictions"][0]["id"]

    result = await resolve_contradiction(
        runtime,
        {"session_id": session.session_id, "contradiction_ids": [contradiction_id]},
    )

    assert result["operations"] == [
        {"type": "remove_relation", "relation_id": "rel-contradicts"}
    ]
    assert "commit_result" not in result

    # Nothing was actually committed.
    relation_ids = {r.identity.id for r in session.knowledge_structure.relations()}
    assert "rel-contradicts" in relation_ids


async def test_resolve_contradiction_mutual_exclusion_commit():
    from cks import parse

    from cks_mcp.tools.resolve_contradiction.handler import resolve_contradiction

    runtime = _real_runtime()
    structure = parse(_MUTUAL_EXCLUSION_JSON)
    session = await runtime.create_session(structure)

    listing = await resolve_contradiction(runtime, {"session_id": session.session_id})
    contradiction_id = listing["contradictions"][0]["id"]

    result = await resolve_contradiction(
        runtime,
        {
            "session_id": session.session_id,
            "contradiction_ids": [contradiction_id],
            "commit": True,
        },
    )

    assert "commit_result" in result
    assert result["commit_result"].get("evolved") is True

    # The alphabetically-first relation id ('rel-contradicts' < 'rel-supports')
    # was removed; the contradiction no longer exists.
    relation_ids = {r.identity.id for r in session.knowledge_structure.relations()}
    assert "rel-contradicts" not in relation_ids
    assert "rel-supports" in relation_ids

    followup = await resolve_contradiction(runtime, {"session_id": session.session_id})
    assert followup["contradiction_count"] == 0


async def test_resolve_contradiction_functional_relation_commit():
    from cks import parse

    from cks_mcp.tools.resolve_contradiction.handler import resolve_contradiction

    runtime = _real_runtime()
    structure = parse(_FUNCTIONAL_RELATION_JSON)
    session = await runtime.create_session(structure)

    listing = await resolve_contradiction(runtime, {"session_id": session.session_id})
    contradiction_id = listing["contradictions"][0]["id"]

    result = await resolve_contradiction(
        runtime,
        {
            "session_id": session.session_id,
            "contradiction_ids": [contradiction_id],
            "commit": True,
        },
    )

    assert "commit_result" in result
    assert result["commit_result"].get("evolved") is True

    relation_ids = {r.identity.id for r in session.knowledge_structure.relations()}
    assert "rel-orbits-mars" not in relation_ids
    assert "rel-orbits-sun" in relation_ids

    followup = await resolve_contradiction(runtime, {"session_id": session.session_id})
    assert followup["contradiction_count"] == 0


async def test_resolve_contradiction_unknown_id_reports_error():
    from cks import parse

    from cks_mcp.tools.resolve_contradiction.handler import resolve_contradiction

    runtime = _real_runtime()
    structure = parse(_MUTUAL_EXCLUSION_JSON)
    session = await runtime.create_session(structure)

    result = await resolve_contradiction(
        runtime,
        {
            "session_id": session.session_id,
            "contradiction_ids": ["does-not-exist"],
            "commit": True,
        },
    )

    assert result["results"] == [
        {
            "contradiction_id": "does-not-exist",
            "error": "contradiction_not_found",
            "message": (
                "Contradiction 'does-not-exist' was not found in session "
                f"'{session.session_id}' -- it may have already been "
                "resolved by an earlier resolution, or the id does not "
                "match any current violation's location."
            ),
        }
    ]
    assert result["operations"] == []
    assert "commit_result" not in result


async def test_resolve_contradiction_invalid_contradiction_ids_type():
    from cks import parse

    from cks_mcp.tools.resolve_contradiction.handler import resolve_contradiction

    runtime = _real_runtime()
    structure = parse(_MUTUAL_EXCLUSION_JSON)
    session = await runtime.create_session(structure)

    result = await resolve_contradiction(
        runtime,
        {"session_id": session.session_id, "contradiction_ids": "not-a-list"},
    )
    assert result["error"] == "invalid_parameter"
