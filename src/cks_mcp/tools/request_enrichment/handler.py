"""
request_enrichment: enqueue an enrichment_request task for the
Enrichment Agent to pick up. Reuses the same generic enqueue_task
storage method that gossip/inference conflict dual-writes already use
(see observability.py/gossip.py), writing directly rather than calling
any separate MCP tool.
"""

from __future__ import annotations

import json
from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.errors import internal_error, missing_parameter


async def request_enrichment(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    session_id = arguments.get("session_id")
    object_id = arguments.get("object_id")

    if not session_id:
        return missing_parameter("session_id")
    if not object_id:
        return missing_parameter("object_id")

    if not runtime.storage.supports_outbox:
        return {
            "enqueued": False,
            "supported": False,
            "message": (
                "This storage backend does not support the persistent outbox "
                "(e.g. the default InMemoryStorage). The Enrichment Agent "
                "requires a shared SQLite or Postgres backend."
            ),
        }

    session = runtime.get_session(session_id)
    if session is None:
        return internal_error(f"session '{session_id}' not found")

    query = arguments.get("query") or None

    await runtime.storage.enqueue_task(
        task_type="enrichment_request",
        session_id=session_id,
        payload=json.dumps(
            {"object_id": object_id, "query": query}
        ),
    )

    return {
        "enqueued": True,
        "supported": True,
        "session_id": session_id,
        "object_id": object_id,
    }