"""
complete_conflict_task: mark a task claimed via ``claim_conflict_task``
as successfully resolved, removing it from the outbox for good.
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime


async def complete_conflict_task(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Complete (delete) a claimed outbox task."""
    task_id = arguments["task_id"]

    if not runtime.storage.supports_outbox:
        return {"completed": False, "supported": False}

    await runtime.storage.complete_outbox_task(task_id)
    return {"completed": True, "supported": True, "task_id": task_id}
