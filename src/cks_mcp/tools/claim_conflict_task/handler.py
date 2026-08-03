"""
claim_conflict_task: atomically claim the next PENDING task of a given
``task_type`` from the persistent outbox (``cks_outbox_tasks``).

This is the Critic-agent-as-a-separate-process counterpart to
``list_gossip_conflicts``/``list_inference_conflicts``: those two read
the in-process ``ConflictInbox`` singleton, which a genuinely separate
OS process (its own Runtime, its own empty ConflictInbox) can never
see. Gossip/inference conflicts are also dual-written into the shared
outbox (see ``gossip.py``/``observability.py``) under task_type
``"gossip_conflict"``/``"inference_conflict"`` whenever the storage
backend supports it (``supports_outbox``) -- this tool is how an
external Critic-agent process reads that shared queue instead.

Unlike ``list_gossip_conflicts``' batch peek/drain, this claims exactly
one task at a time (``dequeue_next_outbox_task``), marking it
``IN_PROGRESS`` so a second Critic-agent process polling concurrently
can never claim the same task -- the natural shape for a worker loop
that processes one conflict, then calls ``complete_conflict_task``/
``fail_conflict_task``/``dead_letter_conflict_task`` before claiming
the next.
"""

from __future__ import annotations

import json
from typing import Any

from cks_runtime.runtime import Runtime


async def claim_conflict_task(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Claim the next eligible task of the given task_type, if any."""
    task_type = arguments["task_type"]

    if not runtime.storage.supports_outbox:
        return {
            "task": None,
            "supported": False,
            "message": (
                "This storage backend does not support the persistent outbox "
                "(e.g. the default InMemoryStorage). A separate Critic-agent "
                "process requires a shared SQLite or Postgres backend to see "
                "conflicts across processes -- see list_gossip_conflicts/"
                "list_inference_conflicts for same-process access instead."
            ),
        }

    task = await runtime.storage.dequeue_next_outbox_task(task_type=task_type)
    if task is None:
        return {"task": None, "supported": True}

    try:
        payload = json.loads(task.payload)
    except (json.JSONDecodeError, TypeError):
        payload = task.payload

    return {
        "task": {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "session_id": task.session_id,
            "payload": payload,
            "retry_count": task.retry_count,
        },
        "supported": True,
    }
