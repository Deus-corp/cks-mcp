"""
export_storage: dump the entire runtime storage to a JSON file on disk.

This is a mechanical tool (no LLM) — it calls export_storage() on the
storage backend, writes the result to a file, and returns a summary.
The full dump is never echoed into the MCP response to avoid overwhelming
the caller with potentially huge payloads.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from datetime import UTC, datetime
from typing import Any

from cks_runtime.runtime import Runtime


async def export_storage(
    runtime: Runtime, arguments: dict[str, Any]
) -> dict[str, Any]:
    include_embeddings: bool = arguments.get("include_embeddings", True)
    output_path: str | None = arguments.get("output_path")

    try:
        dump = await runtime.storage.export_storage()
    except NotImplementedError:
        return {
            "error": "not_supported",
            "message": (
                "The current storage backend does not support export_storage. "
                "Only SQLiteStorage and InMemoryStorage implement this operation."
            ),
        }

    if not include_embeddings:
        dump = {**dump, "embeddings": []}

    session_count = len(dump.get("sessions", []))
    version_count = len(dump.get("versions", []))
    graph_count = len(dump.get("graphs", []))
    embedding_count = len(dump.get("embeddings", []))
    task_count = len(dump.get("outbox_tasks", []))

    if output_path is None:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        filename = f"cks_backup_{ts}.json"
        output_path = os.path.join(tempfile.gettempdir(), filename)

    def _write_dump():
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(dump, fh, ensure_ascii=False, indent=2)
    await asyncio.to_thread(_write_dump)

    return {
        "file_path": output_path,
        "summary": {
            "sessions": session_count,
            "versions": version_count,
            "graphs": graph_count,
            "embeddings": embedding_count,
            "outbox_tasks": task_count,
            "exported_at": dump.get("exported_at"),
        },
    }