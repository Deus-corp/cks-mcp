"""Unit tests for the export_storage MCP tool."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.tools.export_storage.handler import export_storage

pytestmark = pytest.mark.asyncio

_SAMPLE_DUMP = {
    "version": 1,
    "exported_at": "2025-01-01T00:00:00Z",
    "sessions": ['{"session_id": "s1"}', '{"session_id": "s2"}'],
    "versions": ['{"version_id": "v1"}'],
    "graphs": [{"name": "g1", "session_id": "s1"}],
    "embeddings": [],
    "outbox_tasks": [],
}


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.export_storage = AsyncMock(return_value=_SAMPLE_DUMP)
    return runtime


async def test_returns_summary_and_file_path(mock_runtime, tmp_path):
    out = str(tmp_path / "dump.json")
    result = await export_storage(mock_runtime, {"output_path": out})

    assert result["file_path"] == out
    assert result["summary"]["sessions"] == 2
    assert result["summary"]["versions"] == 1
    assert result["summary"]["graphs"] == 1
    assert result["summary"]["embeddings"] == 0


async def test_writes_valid_json_file(mock_runtime, tmp_path):
    out = str(tmp_path / "dump.json")
    await export_storage(mock_runtime, {"output_path": out})

    with open(out) as fh: # noqa: ASYNC230
        data = json.load(fh)
    assert data["version"] == 1
    assert len(data["sessions"]) == 2


async def test_uses_tmpdir_when_no_output_path(mock_runtime):
    result = await export_storage(mock_runtime, {})
    assert os.path.isfile(result["file_path"])
    assert "cks_backup_" in os.path.basename(result["file_path"])
    os.remove(result["file_path"])


async def test_exclude_embeddings(mock_runtime, tmp_path):
    dump_with_emb = {**_SAMPLE_DUMP, "embeddings": [{"object_id": "o1", "session_id": "s1", "embedding_b64": "AAAA"}]}
    mock_runtime.storage.export_storage = AsyncMock(return_value=dump_with_emb)

    out = str(tmp_path / "dump.json")
    result = await export_storage(mock_runtime, {"output_path": out, "include_embeddings": False})

    assert result["summary"]["embeddings"] == 0
    with open(out) as fh: # noqa: ASYNC230
        data = json.load(fh)
    assert data["embeddings"] == []


async def test_not_supported_backend(tmp_path):
    runtime = MagicMock()
    runtime.storage.export_storage = AsyncMock(side_effect=NotImplementedError)

    result = await export_storage(runtime, {})
    assert result["error"] == "not_supported"