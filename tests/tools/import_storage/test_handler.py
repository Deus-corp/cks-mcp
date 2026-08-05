"""Unit tests for the import_storage MCP tool."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.tools.import_storage.handler import import_storage

pytestmark = pytest.mark.asyncio

_VALID_DUMP = {
    "version": 1,
    "exported_at": "2025-01-01T00:00:00Z",
    "sessions": ["s1_data"],
    "versions": ["v1_data"],
    "graphs": [{"name": "g1"}],
    "embeddings": [],
    "outbox_tasks": [],
}


def _write_dump(path: str, content: dict) -> None:
    with open(path, "w") as fh:
        json.dump(content, fh)


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.import_storage = AsyncMock(return_value=None)
    return runtime


@pytest.fixture
def dump_file(tmp_path):
    p = str(tmp_path / "dump.json")
    _write_dump(p, _VALID_DUMP)
    return p


async def test_missing_file_path(mock_runtime):
    result = await import_storage(mock_runtime, {})
    assert result["error"] == "missing_parameter"


async def test_file_not_found(mock_runtime):
    result = await import_storage(mock_runtime, {"file_path": "/nonexistent/dump.json"})
    assert result["error"] == "file_not_found"


async def test_invalid_json(mock_runtime, tmp_path):
    bad = str(tmp_path / "bad.json")
    with open(bad, "w") as fh: # noqa: ASYNC230
        fh.write("NOT JSON {{{{")
    result = await import_storage(mock_runtime, {"file_path": bad})
    assert result["error"] == "invalid_json"


async def test_invalid_format_missing_version(mock_runtime, tmp_path):
    p = str(tmp_path / "dump.json")
    _write_dump(p, {"sessions": []})  # no version key
    result = await import_storage(mock_runtime, {"file_path": p})
    assert result["error"] == "invalid_format"


async def test_invalid_mode(mock_runtime, dump_file):
    result = await import_storage(mock_runtime, {"file_path": dump_file, "mode": "overwrite"})
    assert result["error"] == "invalid_parameter"


async def test_successful_merge(mock_runtime, dump_file):
    result = await import_storage(mock_runtime, {"file_path": dump_file, "mode": "merge"})
    assert "imported" in result
    assert result["imported"]["sessions"] == 1
    assert result["imported"]["versions"] == 1
    assert result["imported"]["graphs"] == 1
    assert result["mode"] == "merge"
    mock_runtime.storage.import_storage.assert_awaited_once()
    _, _kwargs = mock_runtime.storage.import_storage.call_args
    # mode passed correctly
    assert "merge" in mock_runtime.storage.import_storage.call_args[0] or \
           mock_runtime.storage.import_storage.call_args[1].get("mode") == "merge" or \
           mock_runtime.storage.import_storage.call_args[0][1] == "merge"


async def test_successful_clear(mock_runtime, dump_file):
    result = await import_storage(mock_runtime, {"file_path": dump_file, "mode": "clear"})
    assert result["mode"] == "clear"


async def test_not_supported_backend(dump_file):
    runtime = MagicMock()
    runtime.storage.import_storage = AsyncMock(side_effect=NotImplementedError)
    result = await import_storage(runtime, {"file_path": dump_file})
    assert result["error"] == "not_supported"


async def test_default_mode_is_merge(mock_runtime, dump_file):
    result = await import_storage(mock_runtime, {"file_path": dump_file})
    assert result["mode"] == "merge"