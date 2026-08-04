"""Unit tests for the resolve_temporal_conflict MCP tool."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cks.core import KnowledgeObject, KnowledgeStructure, ObjectIdentity

pytestmark = pytest.mark.asyncio


def _obj(oid: str, otype: str = "Claim", **structure) -> KnowledgeObject:
    return KnowledgeObject(
        identity=ObjectIdentity(id=oid, type=otype, name=oid),
        structure=dict(structure),
    )


def _make_session(session_id: str, *objects: KnowledgeObject) -> MagicMock:
    session = MagicMock()
    session.session_id = session_id
    session.knowledge_structure = KnowledgeStructure(list(objects))
    return session


def _make_runtime(session: MagicMock | None) -> MagicMock:
    runtime = MagicMock()
    runtime.get_session.return_value = session
    return runtime


class TestValidation:
    async def test_missing_session_id(self):
        from cks_mcp.tools.resolve_temporal_conflict.handler import (
            resolve_temporal_conflict,
        )

        result = await resolve_temporal_conflict(MagicMock(), {"object_id": "o1"})
        assert result["error"] == "missing_parameter"

    async def test_missing_object_id(self):
        from cks_mcp.tools.resolve_temporal_conflict.handler import (
            resolve_temporal_conflict,
        )

        result = await resolve_temporal_conflict(MagicMock(), {"session_id": "s1"})
        assert result["error"] == "missing_parameter"

    async def test_unknown_action(self):
        from cks_mcp.tools.resolve_temporal_conflict.handler import (
            resolve_temporal_conflict,
        )

        result = await resolve_temporal_conflict(
            MagicMock(),
            {"session_id": "s1", "object_id": "o1", "action": "delete"},
        )
        assert result["error"] == "invalid_parameter"

    async def test_session_not_found(self):
        from cks_mcp.tools.resolve_temporal_conflict.handler import (
            resolve_temporal_conflict,
        )

        runtime = _make_runtime(None)
        result = await resolve_temporal_conflict(
            runtime, {"session_id": "missing", "object_id": "o1"}
        )
        assert result["error"] == "session_not_found"

    async def test_object_not_found(self):
        from cks_mcp.tools.resolve_temporal_conflict.handler import (
            resolve_temporal_conflict,
        )

        session = _make_session("s1", _obj("other-obj", valid_until="2020-01-01T00:00:00Z"))
        runtime = _make_runtime(session)
        result = await resolve_temporal_conflict(
            runtime, {"session_id": "s1", "object_id": "o1", "action": "ignore"}
        )
        assert result["error"] == "object_not_found"

    async def test_bump_missing_extend_by_days(self):
        from cks_mcp.tools.resolve_temporal_conflict.handler import (
            resolve_temporal_conflict,
        )

        session = _make_session("s1", _obj("o1", valid_until="2020-01-01T00:00:00Z"))
        runtime = _make_runtime(session)
        result = await resolve_temporal_conflict(
            runtime, {"session_id": "s1", "object_id": "o1", "action": "bump"}
        )
        assert result["error"] == "missing_parameter"

    async def test_bump_non_positive_extend_by_days(self):
        from cks_mcp.tools.resolve_temporal_conflict.handler import (
            resolve_temporal_conflict,
        )

        session = _make_session("s1", _obj("o1", valid_until="2020-01-01T00:00:00Z"))
        runtime = _make_runtime(session)
        result = await resolve_temporal_conflict(
            runtime,
            {
                "session_id": "s1",
                "object_id": "o1",
                "action": "bump",
                "extend_by_days": -3,
            },
        )
        assert result["error"] == "invalid_parameter"


class TestIgnore:
    async def test_ignore_is_a_pure_acknowledgment(self):
        from cks_mcp.tools.resolve_temporal_conflict.handler import (
            resolve_temporal_conflict,
        )

        session = _make_session("s1", _obj("o1", valid_until="2020-01-01T00:00:00Z"))
        runtime = _make_runtime(session)
        with patch(
            "cks_mcp.tools.resolve_temporal_conflict.handler.evolve_knowledge",
            AsyncMock(),
        ) as mock_evolve:
            result = await resolve_temporal_conflict(
                runtime,
                {
                    "session_id": "s1",
                    "object_id": "o1",
                    "action": "ignore",
                    "commit": True,
                },
            )

        mock_evolve.assert_not_awaited()
        assert result["acknowledged"] is True
        assert "operations" not in result

    async def test_default_action_is_ignore(self):
        from cks_mcp.tools.resolve_temporal_conflict.handler import (
            resolve_temporal_conflict,
        )

        session = _make_session("s1", _obj("o1", valid_until="2020-01-01T00:00:00Z"))
        runtime = _make_runtime(session)
        result = await resolve_temporal_conflict(
            runtime, {"session_id": "s1", "object_id": "o1"}
        )
        assert result["action"] == "ignore"
        assert result["acknowledged"] is True


class TestBump:
    async def test_bump_extends_from_now_when_already_expired(self):
        from cks_mcp.tools.resolve_temporal_conflict.handler import (
            resolve_temporal_conflict,
        )

        session = _make_session("s1", _obj("o1", valid_until="2020-01-01T00:00:00Z"))
        runtime = _make_runtime(session)
        before = datetime.now(UTC)

        result = await resolve_temporal_conflict(
            runtime,
            {
                "session_id": "s1",
                "object_id": "o1",
                "action": "bump",
                "extend_by_days": 7,
            },
        )

        new_valid_until = datetime.fromisoformat(result["new_valid_until"])
        assert new_valid_until >= before + timedelta(days=7)
        assert result["previous_valid_until"] == "2020-01-01T00:00:00Z"
        assert result["operations"] == [
            {
                "type": "update_object",
                "object_id": "o1",
                "structure_patch": {"valid_until": result["new_valid_until"]},
                "mode": "merge",
            }
        ]
        assert "commit_result" not in result

    async def test_bump_extends_from_current_valid_until_when_still_future(self):
        from cks_mcp.tools.resolve_temporal_conflict.handler import (
            resolve_temporal_conflict,
        )

        future = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        session = _make_session("s1", _obj("o1", valid_until=future))
        runtime = _make_runtime(session)

        result = await resolve_temporal_conflict(
            runtime,
            {
                "session_id": "s1",
                "object_id": "o1",
                "action": "bump",
                "extend_by_days": 7,
            },
        )

        new_valid_until = datetime.fromisoformat(result["new_valid_until"])
        expected_min = datetime.fromisoformat(future) + timedelta(days=7)
        assert new_valid_until >= expected_min

    async def test_bump_commits_via_evolve_knowledge(self):
        from cks_mcp.tools.resolve_temporal_conflict.handler import (
            resolve_temporal_conflict,
        )

        session = _make_session("s1", _obj("o1", valid_until="2020-01-01T00:00:00Z"))
        runtime = _make_runtime(session)
        evolve_result = {"session_id": "s1", "version_id": "v2"}
        with patch(
            "cks_mcp.tools.resolve_temporal_conflict.handler.evolve_knowledge",
            AsyncMock(return_value=evolve_result),
        ) as mock_evolve:
            result = await resolve_temporal_conflict(
                runtime,
                {
                    "session_id": "s1",
                    "object_id": "o1",
                    "action": "bump",
                    "extend_by_days": 14,
                    "commit": True,
                },
            )

        mock_evolve.assert_awaited_once()
        call_args = mock_evolve.await_args.args
        assert call_args[0] is runtime
        evolve_arguments = call_args[1]
        assert evolve_arguments["session_id"] == "s1"
        assert evolve_arguments["extensions"] == ["temporal_validity"]
        assert evolve_arguments["operations"] == result["operations"]
        assert result["commit_result"] == evolve_result


class TestArchive:
    async def test_archive_marks_object_and_clears_valid_until(self):
        from cks_mcp.tools.resolve_temporal_conflict.handler import (
            resolve_temporal_conflict,
        )

        session = _make_session("s1", _obj("o1", valid_until="2020-01-01T00:00:00Z"))
        runtime = _make_runtime(session)

        result = await resolve_temporal_conflict(
            runtime, {"session_id": "s1", "object_id": "o1", "action": "archive"}
        )

        assert result["operations"] == [
            {
                "type": "update_object",
                "object_id": "o1",
                "structure_patch": {
                    "archived": True,
                    "archived_at": result["archived_at"],
                    "valid_until": None,
                },
                "mode": "merge",
            }
        ]
        assert "commit_result" not in result

    async def test_archive_commits_via_evolve_knowledge(self):
        from cks_mcp.tools.resolve_temporal_conflict.handler import (
            resolve_temporal_conflict,
        )

        session = _make_session("s1", _obj("o1", valid_until="2020-01-01T00:00:00Z"))
        runtime = _make_runtime(session)
        evolve_result = {"session_id": "s1", "version_id": "v2"}
        with patch(
            "cks_mcp.tools.resolve_temporal_conflict.handler.evolve_knowledge",
            AsyncMock(return_value=evolve_result),
        ) as mock_evolve:
            result = await resolve_temporal_conflict(
                runtime,
                {
                    "session_id": "s1",
                    "object_id": "o1",
                    "action": "archive",
                    "commit": True,
                },
            )

        mock_evolve.assert_awaited_once()
        assert result["commit_result"] == evolve_result