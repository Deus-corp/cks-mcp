"""
register_graph: register (or update) a ``name -> session_id`` mapping
in the graph registry, so a previously-built Knowledge Graph can be
looked up by a memorable name in a later session -- by this LLM or a
person -- instead of being rebuilt from scratch. Registering an
already-used ``name`` replaces its existing entry (last write wins).

``public`` (Memory Agent v2) opts the graph into the gallery --
discoverable by other callers via ``list_graphs(public_only=True)``/
``search_graphs``, not just by name via ``get_graph``. Defaults to
``False``.
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
    public = bool(arguments.get("public", False))
    source_graph_name = arguments.get("source_graph_name") or None
    visibility = arguments.get("visibility") or None
    team = arguments.get("team") or None

    if visibility is not None and visibility not in ("private", "team", "public"):
        return {
            "error": "invalid_parameter",
            "message": "visibility must be one of 'private', 'team', 'public'.",
        }
    if visibility == "team" and not team:
        return {
            "error": "missing_parameter",
            "message": "visibility='team' requires a `team` name.",
        }

    await runtime.storage.register_graph(
        name=name,
        session_id=session_id,
        description=description,
        tags=tags,
        public=public,
        source_graph_name=source_graph_name,
        visibility=visibility,
        team=team,
    )

    resolved_visibility = visibility or ("public" if public else "private")
    return {
        "registered": True,
        "name": name,
        "public": resolved_visibility == "public",
        "visibility": resolved_visibility,
        "team": team,
    }