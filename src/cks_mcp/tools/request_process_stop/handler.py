"""
request_process_stop: request that the most-recently-started instance
of a given standalone-agent process_kind stop gracefully (see
cks-runtime ADR-016, cks-mcp ADR-010).
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime


async def request_process_stop(
    runtime: Runtime, arguments: dict[str, Any]
) -> dict[str, Any]:
    """See REQUEST_PROCESS_STOP_SCHEMA['description'] for the shape of
    the response and what an unrecognized/never-seen process_kind
    returns.

    Looks up the most-recently-started instance the same way
    ``process_status`` does -- ``list_agent_liveness`` is documented to
    return most-recently-started first, so the first matching record is
    the one to target. Does not filter by computed alive/stopped status
    itself: if the "found" instance is actually already stopped (stale
    heartbeat), ``request_agent_stop`` still succeeds as a harmless
    no-op write (the process is gone, nothing reads the flag again),
    matching ADR-010's "no-op either way" framing for that case.
    """
    process_kind = arguments["process_kind"]
    records = await runtime.storage.list_agent_liveness()
    for r in records:
        if r.process_kind == process_kind:
            accepted = await runtime.storage.request_agent_stop(r.instance_id)
            return {
                "process_kind": process_kind,
                "instance_id": r.instance_id,
                "accepted": accepted,
            }
    return {"process_kind": process_kind, "found": False}