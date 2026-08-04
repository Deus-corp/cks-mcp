"""
list_graphs: list every registered graph, optionally filtered by tag,
so a caller can browse what's available before deciding which one to
resume with get_graph.
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime


async def list_graphs(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    tag = arguments.get("tag") or None

    graphs = await runtime.storage.list_graphs(tag)

    return {"graphs": graphs}
