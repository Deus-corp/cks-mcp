"""
unregister_graph: remove a ``name -> session_id`` mapping from the
graph registry (Gallery), so a previously-registered graph is no
longer discoverable via list_graphs/search_graphs or resolvable via
get_graph.

This does not delete the underlying session or its Knowledge
Structure -- only the registry entry. The session remains addressable
by session id.
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.errors import graph_not_found, missing_parameter


async def unregister_graph(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    name = arguments.get("name")
    if not name:
        return missing_parameter("name")

    removed = await runtime.storage.unregister_graph(name)
    if not removed:
        return graph_not_found(name)

    return {"unregistered": True, "name": name}