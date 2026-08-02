"""
visualize_graph: export a subgraph as a Mermaid diagram.

Many MCP clients render Mermaid diagrams natively; if yours doesn't,
the raw Mermaid text is still useful as structured output.

Two modes, dispatched on the ``mode`` argument:

- "structure" (default): objects connected by CanonicalRelations, via
  query_subgraph. Use this after query_subgraph to show the structure.
- "inference": the directed reasoning chain(s) behind one or more
  objects, via explain_inference (ADR-001) -- InferenceSteps connecting
  premises to a conclusion. Use this after
  explain_knowledge(object_id=...) to show *why* something is believed.
"""

from __future__ import annotations

from typing import Any

from cks_runtime.operations.operation_types import ExplainInferenceOperation
from cks_runtime.runtime import Runtime

from cks_mcp.errors import (
    internal_error,
    invalid_parameter,
    missing_parameter,
    session_not_found,
)
from cks_mcp.tools.query_subgraph.handler import query_subgraph_tool
from cks_mcp.tools.visualize_graph.inference import InferenceGraphBuilder

_MODES = ("structure", "inference")

_EMPTY_RESULT = {
    "mermaid": "graph TD\n    empty[Empty graph]",
    "total_found_nodes": 0,
    "returned_nodes": 0,
    "is_truncated": False,
}


async def visualize_graph(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Export a session's Knowledge Structure, a subgraph, or an inference chain as Mermaid."""
    session_id = arguments.get("session_id")
    if not session_id:
        return missing_parameter("session_id")

    session = runtime.get_session(session_id)
    if not session:
        return session_not_found(session_id)

    mode = arguments.get("mode", "structure")
    if mode not in _MODES:
        return invalid_parameter("mode", mode, list(_MODES))

    if mode == "inference":
        return await _visualize_inference(runtime, session, arguments)
    return await _visualize_structure(runtime, session, session_id, arguments)


async def _visualize_structure(
    runtime: Runtime, session: Any, session_id: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Objects connected by CanonicalRelations, via query_subgraph (the original mode)."""
    seed_ids = arguments.get("seed_ids")
    depth = int(arguments.get("depth", 1))
    max_objects = int(arguments.get("max_objects", 20))

    # Always use query_subgraph in compact mode for consistent handling
    # of max_objects, metadata, and node/edge extraction.
    if seed_ids is None:
        # When no seeds are given, treat every non-relation object as a seed
        # with depth=0, so max_objects limits total nodes in a predictable way.
        from cks.core import CanonicalRelation

        seed_ids = [
            obj.identity.id
            for obj in session.knowledge_structure.objects
            if not isinstance(obj, CanonicalRelation)
        ]
        depth = 0

    subgraph_result = await query_subgraph_tool(
        runtime,
        {
            "session_id": session_id,
            "seed_ids": seed_ids,
            "depth": depth,
            "max_objects": max_objects,
            "compact_mode": True,
        },
    )

    if "error" in subgraph_result:
        return subgraph_result

    # subgraph_result["subgraph"] is guaranteed to have "nodes" and "edges"
    # because compact_mode=True was requested.
    subgraph = subgraph_result["subgraph"]
    nodes = subgraph.get("nodes", [])
    edges = subgraph.get("edges", [])

    if not nodes:
        return dict(_EMPTY_RESULT)

    # Build safe aliases for every node, so that IDs containing spaces,
    # colons, brackets, or hyphens don't break Mermaid syntax.
    safe_alias: dict[str, str] = {}
    for i, node in enumerate(nodes):
        safe_alias[node["id"]] = f"n{i}"

    lines = ["graph TD"]
    for node in nodes:
        alias = safe_alias[node["id"]]
        label = f"{node['name']} ({node['type']})".replace('"', "#quot;")
        lines.append(f'    {alias}["{label}"]')

    for edge in edges:
        src = safe_alias.get(edge["source"])
        tgt = safe_alias.get(edge["target"])
        if src is None or tgt is None:
            continue
        rel_type = edge["type"].replace('"', "#quot;")
        lines.append(f'    {src} -->|"{rel_type}"| {tgt}')

    return {
        "mermaid": "\n".join(lines),
        "total_found_nodes": subgraph_result.get("total_found_nodes", len(nodes)),
        "returned_nodes": subgraph_result.get("returned_nodes", len(nodes)),
        "is_truncated": subgraph_result.get("is_truncated", False),
    }


async def _visualize_inference(
    runtime: Runtime, session: Any, arguments: dict[str, Any]
) -> dict[str, Any]:
    """
    Directed reasoning chain(s) behind one or more objects, via
    explain_inference (ADR-001).

    ``explain_inference`` returns each target's *entire* recursive chain
    in one call, so every target_id below is explained at most once --
    including implicitly: a target that was already reached as someone
    else's premise earlier in this same call is skipped, since it was
    already fully walked as part of that premise's payload.
    """
    if not runtime.core_bridge.supports_explain_inference:
        return internal_error(
            "explain_inference is not supported by the attached Core "
            "implementation, so mode='inference' is unavailable here. "
            "Use mode='structure' instead."
        )

    structure = session.knowledge_structure
    seed_ids = arguments.get("seed_ids")
    max_objects = int(arguments.get("max_objects", 20))
    include_superseded = bool(arguments.get("include_superseded", False))

    if seed_ids is None:
        # No explicit targets: every distinct conclusion currently drawn
        # by an active InferenceStep is a belief with a "why" to show.
        target_ids: list[str] = []
        seen_targets: set[str] = set()
        for obj in structure.objects:
            if obj.identity.type != "InferenceStep":
                continue
            conclusion = obj.structure.get("conclusion")
            if conclusion and conclusion not in seen_targets:
                seen_targets.add(conclusion)
                target_ids.append(conclusion)
    else:
        target_ids = list(seed_ids)

    builder = InferenceGraphBuilder(
        structure, max_objects=max_objects, include_superseded=include_superseded
    )

    unexplored_targets = 0
    for target_id in target_ids:
        if target_id in builder.seen_ids:
            continue
        if builder.budget_exceeded:
            unexplored_targets += 1
            continue

        result = await runtime.executor.execute(
            ExplainInferenceOperation(
                "explain_inference",
                knowledge_structure=structure,
                object_id=target_id,
            ),
            session,
        )
        if not result.succeeded:
            # Don't let one bad target (Core-side failure) sink the whole
            # diagram -- show it as a bare, unexplained node and move on.
            builder.add_object(target_id, truncated=None)
            continue
        builder.walk(target_id, result.payload)

    if builder.node_count == 0:
        return dict(_EMPTY_RESULT)

    total_found_nodes = builder.total_seen + unexplored_targets
    returned_nodes = builder.node_count
    return {
        "mermaid": builder.to_mermaid(),
        "total_found_nodes": total_found_nodes,
        "returned_nodes": returned_nodes,
        "is_truncated": total_found_nodes > returned_nodes,
    }