"""
reject_resolution: decline a proposed resolution for a dead-lettered
conflict task, recording why. The task stays DEAD -- this never
retries it (use fail_conflict_task/dead_letter_conflict_task's own
retry semantics for that) and never removes it from the queue (use
approve_resolution/complete_conflict_task for that) -- it only
annotates 'last_error' with the human's reason, for the next reviewer
via review_dead_letter/list_dead_lettered_conflicts.

Reuses storage.dead_letter_outbox_task for the annotation: that method
updates a task's 'last_error' (and clears any stale claimed_at) by
task_id alone, with no precondition on the task's current status --
calling it again on a task that is already DEAD simply overwrites
last_error, which is exactly the mechanical, no-status-transition
behavior this tool needs.
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime


async def reject_resolution(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    task_id = arguments["task_id"]
    reason = arguments.get("reason")

    if not runtime.storage.supports_outbox:
        return {
            "rejected": False,
            "task_id": task_id,
            "error": "not_supported",
            "message": (
                "This storage backend does not support the persistent outbox "
                "(e.g. the default InMemoryStorage) -- there is no dead-letter "
                "queue to reject against."
            ),
        }

    tasks = await runtime.storage.list_dead_letter_tasks()
    task = next((t for t in tasks if t.task_id == task_id), None)
    if task is None:
        return {
            "rejected": False,
            "task_id": task_id,
            "error": "task_not_dead_lettered",
            "message": (
                f"Task {task_id!r} was not found among DEAD-lettered tasks -- "
                "it may not exist, or it may not currently be in the DEAD state."
            ),
        }

    last_error = f"Rejected by human: {reason}" if reason else "Rejected by human."
    await runtime.storage.dead_letter_outbox_task(task_id, last_error)

    return {
        "rejected": True,
        "task_id": task_id,
        "reason": reason,
    }
