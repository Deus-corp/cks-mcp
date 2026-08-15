"""
Shared "resolve a graph side by session id or registry name" helper for
the cross-graph tools (compare_graphs, merge_graphs, link_graphs).

Mirrors clone_graph's own ``_resolve_source`` (same precedence rule:
session id wins when both are given), factored out here since all three
cross-graph tools need it twice per call (once for each side).
"""

from __future__ import annotations

from typing import Any, NamedTuple

from cks_mcp.errors import graph_not_found, missing_parameter, session_not_found


class ResolvedGraph(NamedTuple):
    session: Any
    session_id: str
    graph_name: str | None

    @property
    def label(self) -> str:
        """Best human-readable identifier for error messages/results."""
        return self.graph_name or self.session_id


async def resolve_graph_side(
    runtime: Any,
    arguments: dict[str, Any],
    *,
    name_field: str,
    session_field: str,
) -> ResolvedGraph | dict[str, Any]:
    """
    Resolve one side of a cross-graph call from ``arguments[session_field]``
    (takes precedence) or ``arguments[name_field]`` (looked up in the graph
    registry). Returns a structured error dict on failure.
    """
    session_id = arguments.get(session_field)
    graph_name = arguments.get(name_field)

    if not session_id and not graph_name:
        return missing_parameter(f"{name_field} (or {session_field})")

    resolved_name: str | None = None
    if not session_id:
        assert graph_name is not None  # guaranteed by the check above
        record = await runtime.storage.get_graph(graph_name)
        if record is None:
            return graph_not_found(graph_name)
        session_id = record["session_id"]
        resolved_name = graph_name

    session = runtime.get_session(session_id)
    if session is None:
        return session_not_found(session_id)

    return ResolvedGraph(session=session, session_id=session_id, graph_name=resolved_name)