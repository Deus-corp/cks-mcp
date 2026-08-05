"""
import_storage: restore a JSON backup dump into the current runtime storage.

This is a mechanical tool (no LLM) — it reads the dump file, calls
import_storage() on the backend, and returns a summary of what was restored.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.errors import missing_parameter


async def import_storage(
    runtime: Runtime, arguments: dict[str, Any]
) -> dict[str, Any]:
    file_path: str | None = arguments.get("file_path")
    if not file_path:
        return missing_parameter("file_path")

    mode: str = arguments.get("mode", "merge")
    if mode not in {"merge", "clear"}:
        return {
            "error": "invalid_parameter",
            "message": f"mode must be 'merge' or 'clear', got {mode!r}",
        }

    if not os.path.isfile(file_path):
        return {
            "error": "file_not_found",
            "message": f"No file found at {file_path!r}",
        }

    def _load():
        with open(file_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    try:
        data = await asyncio.to_thread(_load)
    except json.JSONDecodeError as exc:
            return {
                "error": "invalid_json",
                "message": f"Could not parse dump file: {exc}",
            }

    if not isinstance(data, dict) or data.get("version") != 1:
        return {
            "error": "invalid_format",
            "message": (
                "The file does not look like a cks-runtime backup dump "
                "(expected top-level dict with version=1)."
            ),
        }

    try:
        await runtime.storage.import_storage(data, mode=mode)
    except NotImplementedError:
        return {
            "error": "not_supported",
            "message": (
                "The current storage backend does not support import_storage. "
                "Only SQLiteStorage and InMemoryStorage implement this operation."
            ),
        }

    return {
        "imported": {
            "sessions": len(data.get("sessions", [])),
            "versions": len(data.get("versions", [])),
            "graphs": len(data.get("graphs", [])),
            "embeddings": len(data.get("embeddings", [])),
            "outbox_tasks": len(data.get("outbox_tasks", [])),
        },
        "mode": mode,
        "file_path": file_path,
    }