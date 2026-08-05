"""
migrate_storage: copy current runtime storage into a fresh SQLite database.

This is a mechanical tool (no LLM). It:
  1. Exports everything from the current backend via export_storage().
  2. Creates a new SQLiteStorage at target_path.
  3. Imports the dump into it with mode='merge'.
  4. Returns a summary.

Crucially, it does NOT replace runtime.storage — the operator must
restart the server with the new CKS_DB_PATH to activate the new store.
"""

from __future__ import annotations

import os
from typing import Any

from cks_runtime.runtime import Runtime
from cks_runtime.storage.sqlite_storage import SQLiteStorage

from cks_mcp.errors import missing_parameter


async def migrate_storage(
    runtime: Runtime, arguments: dict[str, Any]
) -> dict[str, Any]:
    target_backend: str | None = arguments.get("target_backend")
    target_path: str | None = arguments.get("target_path")

    if not target_backend:
        return missing_parameter("target_backend")
    if not target_path:
        return missing_parameter("target_path")

    if target_backend != "sqlite":
        return {
            "error": "unsupported_backend",
            "message": (
                f"target_backend {target_backend!r} is not supported by this tool. "
                "Only 'sqlite' is available. For Postgres, use export_storage to "
                "get a dump file and then import it via a custom script."
            ),
        }

    if os.path.exists(target_path):
        return {
            "error": "target_exists",
            "message": (
                f"A file already exists at {target_path!r}. "
                "migrate_storage will not overwrite an existing database. "
                "Remove the file or choose a different target_path."
            ),
        }

    # Export from the current backend
    try:
        dump = await runtime.storage.export_storage()
    except NotImplementedError:
        return {
            "error": "not_supported",
            "message": (
                "The current storage backend does not support export_storage. "
                "Only SQLiteStorage and InMemoryStorage can be migrated by this tool."
            ),
        }

    # Create the target SQLite store and import
    target_store = SQLiteStorage(target_path)
    try:
        target_store.import_storage(dump, mode="merge")
    except Exception as exc:
        # Clean up the partially-written file so we don't leave a corrupt DB
        try:
            os.remove(target_path)
        except OSError:
            pass
        return {
            "error": "import_failed",
            "message": str(exc),
        }

    summary = {
        "sessions": len(dump.get("sessions", [])),
        "versions": len(dump.get("versions", [])),
        "graphs": len(dump.get("graphs", [])),
        "embeddings": len(dump.get("embeddings", [])),
        "outbox_tasks": len(dump.get("outbox_tasks", [])),
    }

    return {
        "target_path": target_path,
        "target_backend": target_backend,
        "migrated": summary,
        "note": (
            "Migration complete. To activate the new database, restart the "
            "CKS-MCP server with CKS_STORAGE_BACKEND=sqlite and "
            f"CKS_DB_PATH={target_path}"
        ),
    }