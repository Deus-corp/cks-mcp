"""Unit tests for the refresh_verification MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio

_NEW_RECORD = {
    "identity": {"id": "vr-new", "type": "VerificationRecord", "name": "verification"},
    "structure": {
        "checked_at": "2026-08-04T00:00:00Z",
        "checked_via": "automated_http_check",
        "http_status": 200,
        "cks:signature": "deadbeef",
    },
}
_NEW_RELATION = {
    "identity": {"id": "rel-new", "type": "Relation", "name": "r"},
    "structure": {
        "participants": ["doc-1", "vr-new"],
        "relation_type": "verified_by",
    },
}
_VERIFY_SOURCE_RESULT = {"objects": [_NEW_RECORD, _NEW_RELATION]}
_UNSAFE_URL_RESULT = {
    "error": "unsafe_url",
    "message": "Refusing to verify 'http://127.0.0.1': ... No VerificationRecord was created.",
}


def _make_runtime() -> MagicMock:
    """refresh_verification never touches the runtime directly itself --
    session existence/open-state is checked by registry.py's
    require_open_session middleware (not exercised by these
    handler-level tests), and everything else happens inside the
    verify_source/evolve_knowledge calls this handler makes, which are
    mocked out below."""
    return MagicMock()


class TestNoCommit:
    async def test_returns_new_record_without_committing(self):
        from cks_mcp.tools.refresh_verification.handler import refresh_verification

        runtime = _make_runtime()
        with patch(
            "cks_mcp.tools.refresh_verification.handler.verify_source",
            AsyncMock(return_value=_VERIFY_SOURCE_RESULT),
        ) as mock_verify:
            result = await refresh_verification(
                runtime,
                {
                    "session_id": "s1",
                    "record_id": "vr-stale",
                    "subject_id": "doc-1",
                    "source_url": "https://example.com/doc",
                },
            )

        mock_verify.assert_awaited_once_with(
            runtime, {"url": "https://example.com/doc", "subject_id": "doc-1"}
        )
        assert result["stale_record_id"] == "vr-stale"
        assert result["subject_id"] == "doc-1"
        assert result["source_url"] == "https://example.com/doc"
        assert result["new_record"] == _NEW_RECORD
        assert result["objects"] == [_NEW_RECORD, _NEW_RELATION]
        assert "commit_result" not in result

    async def test_auto_resolve_flag_has_no_effect_and_makes_no_llm_call(self):
        """auto_resolve is accepted for call-shape parity with the other
        conflict-resolution tools, but this tool never calls an LLM --
        passing it must not change the result at all."""
        from cks_mcp.tools.refresh_verification.handler import refresh_verification

        runtime = _make_runtime()
        with patch(
            "cks_mcp.tools.refresh_verification.handler.verify_source",
            AsyncMock(return_value=_VERIFY_SOURCE_RESULT),
        ):
            without_flag = await refresh_verification(
                runtime,
                {
                    "session_id": "s1",
                    "record_id": "vr-stale",
                    "subject_id": "doc-1",
                    "source_url": "https://example.com/doc",
                },
            )
            with_flag = await refresh_verification(
                runtime,
                {
                    "session_id": "s1",
                    "record_id": "vr-stale",
                    "subject_id": "doc-1",
                    "source_url": "https://example.com/doc",
                    "auto_resolve": True,
                },
            )
        assert without_flag == with_flag


class TestCommit:
    async def test_commit_applies_via_evolve_knowledge(self):
        from cks_mcp.tools.refresh_verification.handler import refresh_verification

        runtime = _make_runtime()
        evolve_result = {"session_id": "s1", "version_id": "v2"}
        with (
            patch(
                "cks_mcp.tools.refresh_verification.handler.verify_source",
                AsyncMock(return_value=_VERIFY_SOURCE_RESULT),
            ),
            patch(
                "cks_mcp.tools.refresh_verification.handler.evolve_knowledge",
                AsyncMock(return_value=evolve_result),
            ) as mock_evolve,
        ):
            result = await refresh_verification(
                runtime,
                {
                    "session_id": "s1",
                    "record_id": "vr-stale",
                    "subject_id": "doc-1",
                    "source_url": "https://example.com/doc",
                    "commit": True,
                },
            )

        mock_evolve.assert_awaited_once()
        call_args = mock_evolve.await_args.args
        assert call_args[0] is runtime
        evolve_arguments = call_args[1]
        assert evolve_arguments["session_id"] == "s1"
        assert evolve_arguments["extensions"] == ["verification_record"]
        assert evolve_arguments["operations"] == [
            {
                "type": "add_object",
                "identity": _NEW_RECORD["identity"],
                "structure": _NEW_RECORD["structure"],
            },
            {
                "type": "add_relation",
                "identity": _NEW_RELATION["identity"],
                "participants": ["doc-1", "vr-new"],
                "relation_type": "verified_by",
            },
        ]
        assert result["commit_result"] == evolve_result

    async def test_commit_propagates_evolve_knowledge_error(self):
        from cks_mcp.tools.refresh_verification.handler import refresh_verification

        runtime = _make_runtime()
        evolve_error = {"error": "validation_failed", "message": "nope"}
        with (
            patch(
                "cks_mcp.tools.refresh_verification.handler.verify_source",
                AsyncMock(return_value=_VERIFY_SOURCE_RESULT),
            ),
            patch(
                "cks_mcp.tools.refresh_verification.handler.evolve_knowledge",
                AsyncMock(return_value=evolve_error),
            ),
        ):
            result = await refresh_verification(
                runtime,
                {
                    "session_id": "s1",
                    "record_id": "vr-stale",
                    "subject_id": "doc-1",
                    "source_url": "https://example.com/doc",
                    "commit": True,
                },
            )

        assert result["commit_result"] == evolve_error


class TestVerifySourceError:
    async def test_unsafe_url_error_is_surfaced_without_committing(self):
        from cks_mcp.tools.refresh_verification.handler import refresh_verification

        runtime = _make_runtime()
        with (
            patch(
                "cks_mcp.tools.refresh_verification.handler.verify_source",
                AsyncMock(return_value=_UNSAFE_URL_RESULT),
            ),
            patch(
                "cks_mcp.tools.refresh_verification.handler.evolve_knowledge",
                AsyncMock(),
            ) as mock_evolve,
        ):
            result = await refresh_verification(
                runtime,
                {
                    "session_id": "s1",
                    "record_id": "vr-stale",
                    "subject_id": "doc-1",
                    "source_url": "http://127.0.0.1",
                    "commit": True,
                },
            )

        mock_evolve.assert_not_awaited()
        assert result["error"] == "unsafe_url"
        assert result["stale_record_id"] == "vr-stale"
        assert result["subject_id"] == "doc-1"
        assert result["source_url"] == "http://127.0.0.1"
        assert "commit_result" not in result