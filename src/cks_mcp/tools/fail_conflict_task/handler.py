"""
fail_conflict_task: mark a claimed conflict task as transiently failed,
scheduling it for another attempt with exponential backoff -- the same
retry/backoff policy ``OutboxEmbeddingWorker`` uses for projection
tasks, exposed here for a Critic-agent process handling
``gossip_conflict``/``inference_conflict`` tasks.

For a Critic agent that has genuinely given up (not just hit a
transient error), use ``dead_letter_conflict_task`` instead -- that
retires the task for good rather than scheduling another retry.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from cks_runtime.runtime import Runtime

# Same cap as OutboxEmbeddingWorker._process_next_task -- a stuck task
# retries at most once an hour rather than backing off indefinitely.
_MAX_BACKOFF_SECONDS = 3600


async def fail_conflict_task(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Reschedule a claimed task for retry with exponential backoff."""
    task_id = arguments["task_id"]
    retry_count = arguments["retry_count"]
    error = arguments["error"]

    if not runtime.storage.supports_outbox:
        return {"failed": False, "supported": False}

    delay_seconds = min(2**retry_count, _MAX_BACKOFF_SECONDS)
    next_retry_at = (datetime.now(UTC) + timedelta(seconds=delay_seconds)).isoformat()

    await runtime.storage.fail_outbox_task(task_id, retry_count, error, next_retry_at)
    return {
        "failed": True,
        "supported": True,
        "task_id": task_id,
        "retry_count": retry_count,
        "next_retry_at": next_retry_at,
    }
