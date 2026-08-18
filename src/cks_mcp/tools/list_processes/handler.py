"""
list_processes: return every known standalone-agent process instance
and its computed alive/stopped liveness status (see cks-runtime
ADR-014, cks-mcp ADR-008).
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

from cks_runtime.runtime import Runtime

logger = logging.getLogger(__name__)

_LIVENESS_TTL_MULTIPLIER = 3

# cks_agent_liveness rows are upserted forever and never expire on their
# own (see ADR-014) -- a process that dies without a clean shutdown
# leaves a permanently "stopped" row behind. Opportunistically prune
# anything whose heartbeat is older than this rather than requiring a
# separate cleanup job/cron. 7 days keeps recently-dead processes
# visible for troubleshooting while still bounding table growth.
_LIVENESS_PRUNE_AFTER_SECONDS = 7 * 24 * 60 * 60

# Observed in production: this DELETE was being awaited inline on
# *every* list_processes/process_status poll (studio's Agent Control
# Panel polls this every few seconds), and on some storage backends
# under load a single prune took 16-33 seconds -- see issue #8. Two
# changes fix that:
#  1. Only actually run the prune (and only start one) at most once
#     per _PRUNE_THROTTLE_SECONDS, tracked by this monotonic
#     timestamp, so the DELETE isn't reissued on every single poll.
#  2. When it does run, fire it as a background asyncio.Task instead
#     of awaiting it inline, so a slow prune never blocks the read
#     this tool exists to serve. Any exception is logged and
#     swallowed in the task itself (matching the previous try/except
#     semantics) so a background failure can't surface as an
#     unretrieved-exception warning or a crashed task.
_PRUNE_THROTTLE_SECONDS = 5 * 60
# time.monotonic()'s epoch is arbitrary (e.g. system boot on Linux),
# NOT process start -- 0.0 is not "a long time ago" in that clock, so
# it must not be used as the "never pruned yet" sentinel or the very
# first prune can be spuriously throttled. -inf always compares as
# "longer ago than any real timestamp", regardless of the clock's
# arbitrary epoch.
_last_prune_attempt_monotonic: float = float("-inf")
_prune_task: asyncio.Task[None] | None = None


async def _run_prune(runtime: Runtime) -> None:
    try:
        await runtime.storage.prune_agent_liveness(_LIVENESS_PRUNE_AFTER_SECONDS)
    except Exception as exc:  # pragma: no cover - defensive, logged not raised
        logger.warning("prune_agent_liveness failed: %s", exc)


def _maybe_schedule_prune(runtime: Runtime) -> None:
    """Kick off a background prune if enough time has passed since the
    last attempt and no prune is currently in flight. Never awaited by
    callers -- see module docstring above for why."""
    global _last_prune_attempt_monotonic, _prune_task
    if not runtime.storage.supports_agent_liveness:
        return
    if _prune_task is not None and not _prune_task.done():
        return
    now = time.monotonic()
    if now - _last_prune_attempt_monotonic < _PRUNE_THROTTLE_SECONDS:
        return
    _last_prune_attempt_monotonic = now
    _prune_task = asyncio.create_task(_run_prune(runtime))


def _status_for(last_heartbeat_at: str, liveness_interval_s: float) -> str:
    """alive iff the last heartbeat is within 3x the instance's own
    configured liveness_interval -- see ADR-014 §3 for why 3x (not 2x)
    was chosen: slack for one missed tick without flapping, while still
    catching a genuinely dead process within a bounded window."""
    try:
        last = datetime.fromisoformat(last_heartbeat_at)
    except ValueError:
        return "stopped"
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    age_seconds = (datetime.now(UTC) - last).total_seconds()
    return "alive" if age_seconds <= _LIVENESS_TTL_MULTIPLIER * liveness_interval_s else "stopped"


async def list_processes(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """See LIST_PROCESSES_SCHEMA['description'] for the shape of each
    entry and the process-locality caveat (this reads a shared storage
    table, NOT this MCP server's own process state -- unlike
    list_agents)."""
    # Best-effort, throttled, non-blocking; see _maybe_schedule_prune's
    # docstring. Never awaited here -- a prune in flight (or a slow
    # one) must never delay this read.
    _maybe_schedule_prune(runtime)
    records = await runtime.storage.list_agent_liveness()
    processes = [
        {
            "instance_id": r.instance_id,
            "process_kind": r.process_kind,
            "hostname": r.hostname,
            "pid": r.pid,
            "liveness_interval_s": r.liveness_interval_s,
            "started_at": r.started_at,
            "last_heartbeat_at": r.last_heartbeat_at,
            "current_task_id": r.current_task_id,
            "current_task_type": r.current_task_type,
            "status": _status_for(r.last_heartbeat_at, r.liveness_interval_s),
        }
        for r in records
    ]
    return {"processes": processes}