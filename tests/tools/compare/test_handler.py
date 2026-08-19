"""Unit tests for the compare MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

VALID_KNOWLEDGE_JSON = (
    '{"objects":[{"identity":{"id":"obj-1","type":"Definition","name":"Test"},"structure":{}}]}'
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.core_bridge.validate.return_value = MagicMock(
        valid=True, diagnostics=[], metadata={}
    )
    runtime.core_bridge.serialize.return_value = '{"serialized":true}'
    runtime.core_bridge.explain.return_value = {
        "object_count": 1,
        "relation_count": 0,
        "summary": {"test": True},
    }
    # For evolve_knowledge, core_bridge.evolve must return an object with
    # .relations() (called by provenance).
    fake_evolved = MagicMock()
    fake_evolved.relations.return_value = []
    fake_evolved.objects = []
    runtime.core_bridge.evolve.return_value = fake_evolved

    session = MagicMock(session_id="s1", diagnostics=[])
    runtime.create_session = AsyncMock(return_value=session)

    tx = MagicMock(session=session)
    tx.results = [MagicMock(payload='{"serialized":true}')]
    runtime.begin_transaction.return_value = tx

    runtime.commit_transaction = AsyncMock(return_value=MagicMock(version_id="v1"))
    runtime.executor.execute = AsyncMock(return_value=MagicMock(
        succeeded=True,
        payload=fake_evolved,
        status=MagicMock(value="completed")
    ))

    return runtime



async def test_compare_versions_returns_structured_error_on_reconstruction_failure(
    mock_runtime, monkeypatch
):
    """
    A reconstruction failure (e.g. cks-core's AddObject raising "Object
    ... already exists." while replaying a patch chain) must surface as
    a structured {"error": ...} dict, not an unhandled exception -- the
    same contract explain_diff provides.
    """
    from cks_mcp.tools.compare.handler import compare_versions

    session = MagicMock(session_id="s1")
    session.version_history = []
    mock_runtime.get_session.return_value = session

    async def _raise_already_exists(*args, **kwargs):
        raise ValueError("Object 'infer-rose-test-final' already exists.")

    monkeypatch.setattr(
        "cks_mcp.tools.compare.handler.reconstruct_with_retry",
        _raise_already_exists,
    )

    args = {"session_id": "s1", "target_version_id": "v1"}
    result = await compare_versions(mock_runtime, args)

    assert "error" in result
    assert "already exists" in result["error"]
    assert "v1" in result["error"]


async def test_compare_versions(mock_runtime):
    from cks_runtime.versioning.version import RuntimeVersion

    from cks_mcp.tools.compare.handler import compare_versions

    session = MagicMock(session_id="s1")
    session.version_history = [
        RuntimeVersion(session_id="s1", transaction_id="tx1", knowledge_structure={"test": True}, metadata={}, version_id="v1"),
        RuntimeVersion(session_id="s1", transaction_id="tx2", knowledge_structure={"test": True}, metadata={}, version_id="current_v"),
    ]
    mock_runtime.get_session.return_value = session
    mock_runtime.core_bridge.diff.return_value = []
    args = {"session_id": "s1", "target_version_id": "v1"}
    result = await compare_versions(mock_runtime, args)
    assert result["session_id"] == "s1"
    assert result["base_version_id"] == "v1"
    assert result["direction"] == "base_to_current"
    assert "summary" in result
    assert "operations" in result
