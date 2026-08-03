"""
list_dead_lettered_conflicts: read-only listing of conflict tasks a
Critic agent has given up on (``dead_letter_conflict_task``), for a
human or operator tool to review. Never drains -- unlike
``claim_conflict_task``, this is a status report, not a work queue.
"""

from __future__ import annotations

import json
from typing import Any

from cks_runtime.runtime import Runtime


async def list_dead_lettered_conflicts(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return every DEAD-lettered conflict task, oldest first."""
    task_type = arguments.get("task_type")

    if not runtime.storage.supports_outbox:
        return {"tasks": [], "count": 0, "supported": False}

    tasks = await runtime.storage.list_dead_letter_tasks(task_type=task_type)

    result = []
    for task in tasks:
        try:
            payload = json.loads(task.payload)
        except (json.JSONDecodeError, TypeError):
            payload = task.payload
        result.append(
            {
                "task_id": task.task_id,
                "task_type": task.task_type,
                "session_id": task.session_id,
                "payload": payload,
                "retry_count": task.retry_count,
            }
        )

    return {"tasks": result, "count": len(result), "supported": True}
