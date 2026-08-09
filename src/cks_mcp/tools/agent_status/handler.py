"""
agent_status: return the status of a single in-process reasoning
sweeper by agent_id.
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime


async def agent_status(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """See AGENT_STATUS_SCHEMA['description'] for the shape of the
    response and what an unrecognized/disabled agent_id returns."""
    agent_id = arguments["agent_id"]
    status = runtime.get_agent_status(agent_id)
    if status is None:
        return {"agent_id": agent_id, "found": False}
    return status
