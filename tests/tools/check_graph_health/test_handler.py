"""Unit tests for the check_graph_health MCP tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cks_mcp.tools.check_graph_health.handler import check_graph_health

# pyproject.toml sets asyncio_mode = "auto", so async test functions are
# picked up automatically -- no pytestmark needed.


def _record(record_id: str, checked_at: str | None) -> SimpleNamespace:
    structure = {} if checked_at is None else {"checked_at": checked_at}
    return SimpleNamespace(
        identity=SimpleNamespace(id=record_id, type="VerificationRecord", name=None),
        structure=structure,
    )


@dataclass
class _FakeStructure:
    objects: list = field(default_factory=list)
    _relations: list = field(default_factory=list)

    def relations(self):
        return self._relations


def _mock_runtime(*, graph_record=None, session=None):
    runtime = MagicMock()
    runtime.storage.get_graph = AsyncMock(return_value=graph_record)
    runtime.get_session = MagicMock(return_value=session)
    return runtime


def _patch_subchecks(
    *,
    version_result=None,
    freshness_result=None,
    contradictions_result=None,
    dead_letter_result=None,
):
    return (
        patch(
            "cks_mcp.tools.check_graph_health.handler.check_component_versions",
            new=AsyncMock(return_value=version_result or {"found": True, "components": []}),
        ),
        patch(
            "cks_mcp.tools.check_graph_health.handler.check_graph_freshness",
            new=AsyncMock(return_value=freshness_result or {"fresh": True}),
        ),
        patch(
            "cks_mcp.tools.check_graph_health.handler.detect_contradictions",
            new=AsyncMock(
                return_value=contradictions_result or {"contradiction_count": 0, "contradictions": []}
            ),
        ),
        patch(
            "cks_mcp.tools.check_graph_health.handler.list_dead_lettered_conflicts",
            new=AsyncMock(
                return_value=dead_letter_result or {"tasks": [], "count": 0, "supported": True}
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Parameter / graph / session validation
# ---------------------------------------------------------------------------


async def test_missing_name():
    runtime = _mock_runtime()
    result = await check_graph_health(runtime, {})
    assert result.get("error") == "missing_parameter"
    runtime.storage.get_graph.assert_not_called()


async def test_graph_not_found():
    runtime = _mock_runtime(graph_record=None)
    result = await check_graph_health(runtime, {"name": "unknown"})
    assert result == {"found": False}


async def test_session_not_available():
    runtime = _mock_runtime(
        graph_record={"name": "g1", "session_id": "s1"}, session=None
    )
    result = await check_graph_health(runtime, {"name": "g1"})
    assert result["found"] is True
    assert result["error"] == "session_not_available"
    assert result["session_id"] == "s1"


# ---------------------------------------------------------------------------
# Full health score computation
# ---------------------------------------------------------------------------


async def test_perfect_health_score():
    session = SimpleNamespace(
        knowledge_structure=_FakeStructure(objects=[], _relations=[])
    )
    runtime = _mock_runtime(
        graph_record={"name": "g1", "session_id": "s1"}, session=session
    )

    patches = _patch_subchecks(
        version_result={
            "found": True,
            "components": [
                {"component": "cks-core", "status": "up_to_date"},
                {"component": "cks-runtime", "status": "up_to_date"},
            ],
        },
    )
    with patches[0], patches[1], patches[2], patches[3]:
        result = await check_graph_health(runtime, {"name": "g1"})

    assert result["name"] == "g1"
    assert result["session_id"] == "s1"
    assert result["health_score"] == pytest.approx(1.0)
    assert result["metrics"]["version_freshness"] == {
        "up_to_date": 2,
        "total": 2,
        "score": 1.0,
    }
    assert result["metrics"]["ttl_freshness"] == {"fresh": True, "score": 1.0}
    assert result["metrics"]["contradictions"] == {"count": 0, "score": 1.0}
    assert result["metrics"]["verification_coverage"] == {
        "fresh": 0,
        "total": 0,
        "score": 1.0,
    }
    assert result["metrics"]["dead_letter"] == {"count": 0, "score": 1.0}
    assert result["metrics"]["graph_size"] == {"objects": 0, "relations": 0}
    assert "timestamp" in result


async def test_degraded_health_score_matches_weighted_average():
    fresh_ts = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    stale_ts = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    records = [_record("r1", fresh_ts) for _ in range(5)] + [
        _record("r2", stale_ts) for _ in range(2)
    ]
    session = SimpleNamespace(
        knowledge_structure=_FakeStructure(objects=records, _relations=[object()] * 3)
    )
    runtime = _mock_runtime(
        graph_record={"name": "g1", "session_id": "s1"}, session=session
    )

    patches = _patch_subchecks(
        version_result={
            "found": True,
            "components": [
                {"component": "cks-core", "status": "up_to_date"},
                {"component": "cks-runtime", "status": "outdated"},
                {"component": "cks-mcp", "status": "up_to_date"},
            ],
        },
        freshness_result={"fresh": False, "last_updated": "...", "ttl_days": 7.0},
        contradictions_result={"contradiction_count": 2, "contradictions": []},
        dead_letter_result={
            "tasks": [
                {"task_id": 1, "session_id": "s1"},
                {"task_id": 2, "session_id": "s1"},
                {"task_id": 3, "session_id": "other"},
            ],
            "count": 3,
            "supported": True,
        },
    )
    with patches[0], patches[1], patches[2], patches[3]:
        result = await check_graph_health(runtime, {"name": "g1"})

    metrics = result["metrics"]
    assert metrics["version_freshness"] == {"up_to_date": 2, "total": 3, "score": 2 / 3}
    assert metrics["ttl_freshness"] == {"fresh": False, "score": 0.0}
    assert metrics["contradictions"] == {"count": 2, "score": 0.0}
    assert metrics["verification_coverage"] == {"fresh": 5, "total": 7, "score": 5 / 7}
    # Only the two tasks whose session_id matches the graph's session
    # are counted, not the third (different session).
    assert metrics["dead_letter"] == {"count": 2, "score": 0.5}
    assert metrics["graph_size"] == {"objects": 7, "relations": 3}

    expected = (
        0.3 * (2 / 3)
        + 0.1 * 0.0
        + 0.3 * 0.0
        + 0.2 * (5 / 7)
        + 0.1 * 0.5
    )
    assert result["health_score"] == pytest.approx(expected)


async def test_dead_letter_unsupported_storage_scores_full():
    session = SimpleNamespace(
        knowledge_structure=_FakeStructure(objects=[], _relations=[])
    )
    runtime = _mock_runtime(
        graph_record={"name": "g1", "session_id": "s1"}, session=session
    )

    patches = _patch_subchecks(
        dead_letter_result={"tasks": [], "count": 0, "supported": False},
    )
    with patches[0], patches[1], patches[2], patches[3]:
        result = await check_graph_health(runtime, {"name": "g1"})

    assert result["metrics"]["dead_letter"] == {"count": 0, "score": 1.0}


async def test_verification_coverage_malformed_checked_at_counts_as_stale():
    records = [_record("r1", None), _record("r2", "not-a-date")]
    session = SimpleNamespace(
        knowledge_structure=_FakeStructure(objects=records, _relations=[])
    )
    runtime = _mock_runtime(
        graph_record={"name": "g1", "session_id": "s1"}, session=session
    )

    patches = _patch_subchecks()
    with patches[0], patches[1], patches[2], patches[3]:
        result = await check_graph_health(runtime, {"name": "g1"})

    assert result["metrics"]["verification_coverage"] == {
        "fresh": 0,
        "total": 2,
        "score": 0.0,
    }
