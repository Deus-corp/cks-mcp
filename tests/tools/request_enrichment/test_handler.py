"""Unit tests for the request_enrichment MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.tools.request_enrichment.handler import request_enrichment

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.supports_outbox = True
    runtime.storage.enqueue_task = AsyncMock()
    runtime.get_session = MagicMock(return_value=MagicMock())
    return runtime


async def test_missing_session_id(mock_runtime):
    result = await request_enrichment(mock_runtime, {"object_id": "obj-1"})
    assert result.get("error") == "missing_parameter"


async def test_missing_object_id(mock_runtime):
    result = await request_enrichment(mock_runtime, {"session_id": "s1"})
    assert result.get("error") == "missing_parameter"


async def test_unsupported_backend(mock_runtime):
    mock_runtime.storage.supports_outbox = False
    result = await request_enrichment(mock_runtime, {"session_id": "s1", "object_id": "obj-1"})
    assert result["enqueued"] is False
    assert result["supported"] is False


async def test_enqueues_task(mock_runtime):
    result = await request_enrichment(
        mock_runtime, {"session_id": "s1", "object_id": "obj-1", "query": "custom query"}
    )
    assert result["enqueued"] is True
    assert result["supported"] is True
    mock_runtime.storage.enqueue_task.assert_awaited_once()
    kwargs = mock_runtime.storage.enqueue_task.await_args.kwargs
    assert kwargs["task_type"] == "enrichment_request"
    assert kwargs["session_id"] == "s1"
    import json
    payload = json.loads(kwargs["payload"])
    assert payload["object_id"] == "obj-1"
    assert payload["query"] == "custom query"