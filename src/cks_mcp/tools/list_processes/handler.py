"""
list_processes: return every known standalone-agent process instance
and its computed alive/stopped liveness status (see cks-runtime
ADR-014, cks-mcp ADR-008).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from cks_runtime.runtime import Runtime

logger = logging.getLogger(__name__)

_LIVENESS_TTL_MULTIPLIER = 3

# cks_agent_liveness rows are upserted forever and never expire on their
# own (see ADR-014) -- a process that dies without a clean shutdown
# leaves a permanently "stopped" row behind. Opportunistically prune
# anything whose heartbeat is older than this on every list_processes
# call (cheap: a single indexed DELETE) rather than requiring a separate
# cleanup job/cron. 7 days keeps recently-dead processes visible for
# troubleshooting while still bounding table growth.
_LIVENESS_PRUNE_AFTER_SECONDS = 7 * 24 * 60 * 60


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
    if runtime.storage.supports_agent_liveness:
        # Best-effort; a prune failure (e.g. a transient DB hiccup)
        # should never break the read this tool exists to serve.
        try:
            await runtime.storage.prune_agent_liveness(_LIVENESS_PRUNE_AFTER_SECONDS)
        except Exception as exc:
            logger.warning("prune_agent_liveness failed: %s", exc)
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