"""
list_graphs: list every registered graph, optionally filtered by tag
and/or (Memory Agent v2) restricted to public graphs only, so a
caller can browse what's available before deciding which one to
resume with get_graph.
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime


async def list_graphs(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    tag = arguments.get("tag") or None
    public_only = bool(arguments.get("public_only", False))
    team = arguments.get("team") or None

    graphs = await runtime.storage.list_graphs(tag, public_only, team=team)

    return {"graphs": graphs}