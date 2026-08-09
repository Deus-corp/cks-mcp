"""
stop_agent: stop a single in-process reasoning sweeper by agent_id and
persist the override so it stays stopped across a restart of this node
(cks-runtime ADR-015, cks-mcp ADR-009).
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime


async def stop_agent(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """See STOP_AGENT_SCHEMA['description'] for the shape of the
    response and what an unrecognized/disabled agent_id returns.

    Reaches into ``runtime._sweepers`` directly to call ``sweeper.stop()``
    -- same pattern cks-runtime ADR-015 §3 itself documents ("same
    pattern as any other MCP tool reaching into Runtime state"), since
    ``Runtime`` deliberately doesn't expose a start/stop method of its
    own (see the comment above ``list_agent_statuses``).
    """
    agent_id = arguments["agent_id"]
    sweeper = runtime._sweepers.get(agent_id)
    if sweeper is None:
        return {"agent_id": agent_id, "found": False}

    await sweeper.stop()
    await runtime.storage.set_sweeper_desired_running(agent_id, False)
    return sweeper.status()