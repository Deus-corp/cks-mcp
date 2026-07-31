"""Unit tests for the serialize MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

VALID_KNOWLEDGE_JSON = (
    '{"objects":[{"identity":{"id":"obj-1","type":"Definition","name":"Test"},"structure":{}}]}'
)

from cks_mcp.tools.serialize.handler import serialize_knowledge

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



async def test_serialize_knowledge(mock_runtime):
    args = {"json_data": VALID_KNOWLEDGE_JSON}
    result = await serialize_knowledge(mock_runtime, args)
    assert result == '{"serialized":true}'
