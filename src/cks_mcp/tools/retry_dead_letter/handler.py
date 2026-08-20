"""
retry_dead_letter: return a DEAD-lettered conflict task to the PENDING
queue for another processing attempt, once whatever caused it to be
dead-lettered via ``dead_letter_conflict_task`` has been addressed.

This is the requeue counterpart to ``dead_letter_conflict_task`` --
that tool moves a task out of the eligible pool for good; this one
moves it back in, via ``RuntimeStorage.retry_dead_letter_task``.
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime


async def retry_dead_letter(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Move a DEAD task back to PENDING so it can be claimed again."""
    task_id = arguments["task_id"]

    if not runtime.storage.supports_outbox:
        return {
            "retried": False,
            "error": "not_supported",
            "message": (
                "This storage backend does not support the persistent outbox "
                "(e.g. the default InMemoryStorage) -- there is no dead-letter "
                "queue to retry."
            ),
        }

    retried = await runtime.storage.retry_dead_letter_task(task_id)
    if not retried:
        return {
            "retried": False,
            "task_id": task_id,
            "error": "task_not_found",
            "message": (
                f"Task {task_id!r} was not found among DEAD-lettered tasks -- "
                "it may not exist, or it may not currently be in the DEAD "
                "state (see list_dead_lettered_conflicts for the current set)."
            ),
        }

    return {"retried": True, "task_id": task_id}