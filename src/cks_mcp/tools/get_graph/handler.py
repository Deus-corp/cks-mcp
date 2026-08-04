"""
get_graph: look up a registered graph by name, returning its
session_id (and metadata) so the caller can resume work against that
session instead of rebuilding the graph from scratch.
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.errors import missing_parameter


async def get_graph(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    name = arguments.get("name")
    if not name:
        return missing_parameter("name")

    record = await runtime.storage.get_graph(name)
    if record is None:
        return {"found": False}

    return {"found": True, **record}
