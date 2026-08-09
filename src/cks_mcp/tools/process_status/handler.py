"""
process_status: return the status of the most recently-started instance
of a given standalone-agent process_kind (see cks-runtime ADR-014,
cks-mcp ADR-008).
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.tools.list_processes.handler import _status_for

_KNOWN_KINDS = frozenset({"critic", "enrichment", "fork_resolution", "pipeline"})


async def process_status(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """See PROCESS_STATUS_SCHEMA['description'] for the shape of the
    response and what an unrecognized/never-seen process_kind returns."""
    process_kind = arguments["process_kind"]
    records = await runtime.storage.list_agent_liveness()
    # list_agent_liveness already returns most-recently-started first.
    for r in records:
        if r.process_kind == process_kind:
            return {
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
    return {"process_kind": process_kind, "found": False}