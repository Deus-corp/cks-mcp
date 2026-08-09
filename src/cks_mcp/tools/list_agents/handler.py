"""
list_agents: return the status of every currently-enabled in-process
reasoning sweeper.
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime


async def list_agents(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """See LIST_AGENTS_SCHEMA['description'] for the shape of each entry
    and the process-locality caveat (in-process sweepers only, not the
    standalone agent processes)."""
    return {"agents": runtime.list_agent_statuses()}
