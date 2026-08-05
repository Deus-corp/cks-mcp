"""Unit tests for the migrate_storage MCP tool."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cks_mcp.tools.migrate_storage.handler import migrate_storage

pytestmark = pytest.mark.asyncio

_SAMPLE_DUMP = {
    "version": 1,
    "exported_at": "2025-01-01T00:00:00Z",
    "sessions": [],
    "versions": [],
    "graphs": [{"name": "g1", "session_id": "s1", "description": "", "tags": "",
                "public": False, "created_at": "2025-01-01", "updated_at": "2025-01-01"}],
    "embeddings": [],
    "outbox_tasks": [],
}


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.storage.export_storage = AsyncMock(return_value=_SAMPLE_DUMP)
    return runtime


async def test_missing_target_backend(mock_runtime, tmp_path):
    result = await migrate_storage(mock_runtime, {"target_path": str(tmp_path / "new.db")})
    assert result["error"] == "missing_parameter"


async def test_missing_target_path(mock_runtime):
    result = await migrate_storage(mock_runtime, {"target_backend": "sqlite"})
    assert result["error"] == "missing_parameter"


async def test_unsupported_backend(mock_runtime, tmp_path):
    result = await migrate_storage(
        mock_runtime,
        {"target_backend": "postgres", "target_path": "postgresql://localhost/test"},
    )
    assert result["error"] == "unsupported_backend"


async def test_target_already_exists(mock_runtime, tmp_path):
    existing = tmp_path / "existing.db"
    existing.write_text("data")
    result = await migrate_storage(
        mock_runtime,
        {"target_backend": "sqlite", "target_path": str(existing)},
    )
    assert result["error"] == "target_exists"


async def test_successful_sqlite_migration(mock_runtime, tmp_path):
    target = str(tmp_path / "migrated.db")
    result = await migrate_storage(
        mock_runtime,
        {"target_backend": "sqlite", "target_path": target},
    )

    assert result.get("error") is None
    assert result["target_path"] == target
    assert result["target_backend"] == "sqlite"
    assert "migrated" in result
    assert result["migrated"]["graphs"] == 1
    assert "CKS_DB_PATH" in result["note"]
    assert os.path.isfile(target)


async def test_not_supported_export(tmp_path):
    runtime = MagicMock()
    runtime.storage.export_storage = AsyncMock(side_effect=NotImplementedError)
    target = str(tmp_path / "new.db")
    result = await migrate_storage(
        runtime,
        {"target_backend": "sqlite", "target_path": target},
    )
    assert result["error"] == "not_supported"
    assert not os.path.exists(target)


async def test_cleans_up_on_import_failure(mock_runtime, tmp_path):
    target = str(tmp_path / "new.db")

    with patch("cks_mcp.tools.migrate_storage.handler.SQLiteStorage") as MockSQLite:
        instance = MagicMock()
        instance.import_storage.side_effect = RuntimeError("disk full")
        MockSQLite.return_value = instance

        result = await migrate_storage(
            mock_runtime,
            {"target_backend": "sqlite", "target_path": target},
        )

    assert result["error"] == "import_failed"
    assert not os.path.exists(target)