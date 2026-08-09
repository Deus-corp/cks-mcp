"""
start_agent: start a single in-process reasoning sweeper by agent_id and
persist the override so it starts again across a restart of this node
(cks-runtime ADR-015, cks-mcp ADR-009).
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime


async def start_agent(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """See START_AGENT_SCHEMA['description'] for the shape of the
    response, what an unrecognized/disabled agent_id returns, and the
    deliberate start/stop cross-node asymmetry (ADR-015 §3).

    Reaches into ``runtime._sweepers`` directly to call ``sweeper.start()``
    -- see ``stop_agent``'s handler docstring for why.
    """
    agent_id = arguments["agent_id"]
    sweeper = runtime._sweepers.get(agent_id)
    if sweeper is None:
        return {"agent_id": agent_id, "found": False}

    await sweeper.start()
    await runtime.storage.set_sweeper_desired_running(agent_id, True)
    return sweeper.status()