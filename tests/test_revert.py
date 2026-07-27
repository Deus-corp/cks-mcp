"""Unit tests for the revert/list_versions tools (version time-travel)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from cks_mcp.tools.revert import list_versions, revert_version


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.core_bridge.serialize.return_value = '{"serialized":true}'

    session = MagicMock(session_id="s1")
    v1 = MagicMock(
        version_id="v1",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        transaction_id="tx-1",
        metadata={"note": "first"},
    )
    v2 = MagicMock(
        version_id="v2",
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        transaction_id="tx-2",
        metadata={},
    )
    session.version_history = [v1, v2]
    runtime.get_session.return_value = session

    tx = MagicMock(session=session)
    runtime.begin_transaction.return_value = tx
    runtime.commit_transaction.return_value = MagicMock(version_id="v3")

    return runtime


# ---------------------------------------------------------------------------
# list_versions
# ---------------------------------------------------------------------------

def test_list_versions_missing_session_id(mock_runtime):
    result = list_versions(mock_runtime, {})
    assert result == {
        "error": "missing_parameter",
        "message": "Missing required parameter: 'session_id'.",
    }


def test_list_versions_session_not_found(mock_runtime):
    mock_runtime.get_session.return_value = None
    result = list_versions(mock_runtime, {"session_id": "missing"})
    assert result == {
        "error": "session_not_found",
        "message": "Session 'missing' not found.",
    }


def test_list_versions_success(mock_runtime):
    result = list_versions(mock_runtime, {"session_id": "s1"})
    assert result["session_id"] == "s1"
    assert len(result["versions"]) == 2
    assert result["versions"][0]["version_id"] == "v1"
    assert result["versions"][0]["transaction_id"] == "tx-1"
    assert result["versions"][1]["version_id"] == "v2"


def test_list_versions_internal_error_is_structured(mock_runtime):
    # Force an exception inside the try block (e.g. malformed version_history)
    broken_version = MagicMock()
    broken_version.created_at = "not-a-datetime"  # .isoformat() will raise
    mock_runtime.get_session.return_value.version_history = [broken_version]

    result = list_versions(mock_runtime, {"session_id": "s1"})
    assert result["error"] == "internal_error"
    assert "list_versions" in result["message"]


# ---------------------------------------------------------------------------
# revert_version
# ---------------------------------------------------------------------------

def test_revert_version_missing_session_id(mock_runtime):
    result = revert_version(mock_runtime, {"target_version_id": "v1"})
    assert result == {
        "error": "missing_parameter",
        "message": "Missing required parameter: 'session_id'.",
    }


def test_revert_version_missing_target_version_id(mock_runtime):
    result = revert_version(mock_runtime, {"session_id": "s1"})
    assert result == {
        "error": "missing_parameter",
        "message": "Missing required parameter: 'target_version_id'.",
    }


def test_revert_version_session_not_found(mock_runtime):
    mock_runtime.get_session.return_value = None
    result = revert_version(mock_runtime, {"session_id": "missing", "target_version_id": "v1"})
    assert result == {
        "error": "session_not_found",
        "message": "Session 'missing' not found.",
    }


def test_revert_version_success(mock_runtime):
    result = revert_version(mock_runtime, {"session_id": "s1", "target_version_id": "v1"})
    assert result["reverted_to"] == "v1"
    assert result["new_version_id"] == "v3"
    assert result["session_id"] == "s1"
    assert result["serialized"] == '{"serialized":true}'
    mock_runtime.begin_transaction.assert_called_once()
    mock_runtime.commit_transaction.assert_called_once()


def test_revert_version_commit_failure_is_structured(mock_runtime):
    mock_runtime.commit_transaction.side_effect = RuntimeError("target version not found in history")
    result = revert_version(mock_runtime, {"session_id": "s1", "target_version_id": "bogus"})
    assert result["error"] == "internal_error"
    assert "revert_version" in result["message"]
    assert "target version not found in history" in result["message"]