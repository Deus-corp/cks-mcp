"""
register_graph: register (or update) a ``name -> session_id`` mapping
in the graph registry, so a previously-built Knowledge Graph can be
looked up by a memorable name in a later session -- by this LLM or a
person -- instead of being rebuilt from scratch. Registering an
already-used ``name`` replaces its existing entry (last write wins).
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.errors import missing_parameter, session_not_found


async def register_graph(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    name = arguments.get("name")
    session_id = arguments.get("session_id")

    if not name:
        return missing_parameter("name")
    if not session_id:
        return missing_parameter("session_id")

    if runtime.get_session(session_id) is None:
        return session_not_found(session_id)

    description = arguments.get("description") or ""
    tags = arguments.get("tags") or ""

    await runtime.storage.register_graph(
        name=name,
        session_id=session_id,
        description=description,
        tags=tags,
    )

    return {"registered": True, "name": name}
