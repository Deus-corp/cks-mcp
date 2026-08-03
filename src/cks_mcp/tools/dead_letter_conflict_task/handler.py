"""
dead_letter_conflict_task: permanently retire a claimed conflict task
the Critic agent could not resolve with confidence, instead of
scheduling another retry. This is roadmap item 2 ("dead-letter queue
for conflicts the agent can't confidently resolve") -- the task stays
in ``cks_outbox_tasks`` with ``status='DEAD'`` for a human/operator
tool to inspect via ``list_dead_lettered_conflicts``, rather than
either looping forever on ``fail_conflict_task`` or silently vanishing.
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime


async def dead_letter_conflict_task(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Permanently mark a claimed task as DEAD (unresolved)."""
    task_id = arguments["task_id"]
    error = arguments["error"]

    if not runtime.storage.supports_outbox:
        return {"dead_lettered": False, "supported": False}

    await runtime.storage.dead_letter_outbox_task(task_id, error)
    return {"dead_lettered": True, "supported": True, "task_id": task_id}
