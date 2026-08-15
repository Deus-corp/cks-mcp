"""
compare_graphs: read-only structural comparison of two registered graphs
(or live sessions).

Never mutates either source -- KnowledgeStructure is immutable, so simply
reading both sides' knowledge_structure cannot affect them.
"""

from __future__ import annotations

from typing import Any

import cks

from cks_mcp.diffing import field_level_diff
from cks_mcp.graph_resolution import ResolvedGraph, resolve_graph_side


def _is_relation_id(structure: cks.KnowledgeStructure, object_id: str) -> bool:
    obj = structure.get(object_id)
    return isinstance(obj, cks.CanonicalRelation)


async def compare_graphs(runtime: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    resolved_a = await resolve_graph_side(
        runtime, arguments, name_field="graph_a_name", session_field="graph_a_session_id"
    )
    if not isinstance(resolved_a, ResolvedGraph):
        return resolved_a

    resolved_b = await resolve_graph_side(
        runtime, arguments, name_field="graph_b_name", session_field="graph_b_session_id"
    )
    if not isinstance(resolved_b, ResolvedGraph):
        return resolved_b

    include_relations = arguments.get("include_relations", True)

    structure_a = resolved_a.session.knowledge_structure
    structure_b = resolved_b.session.knowledge_structure

    ids_a = {obj.identity.id for obj in structure_a.objects}
    ids_b = {obj.identity.id for obj in structure_b.objects}

    if not include_relations:
        relation_ids_a = {r.identity.id for r in structure_a.relations()}
        relation_ids_b = {r.identity.id for r in structure_b.relations()}
        ids_a -= relation_ids_a
        ids_b -= relation_ids_b

    shared_ids = ids_a & ids_b
    only_in_a = ids_a - ids_b
    only_in_b = ids_b - ids_a

    differences: list[dict[str, Any]] = []
    for object_id in sorted(shared_ids):
        obj_a = structure_a.get(object_id)
        obj_b = structure_b.get(object_id)
        diff = field_level_diff(obj_a, obj_b)
        if diff.get("action") == "modified":
            differences.append({"id": object_id, **diff})

    return {
        "graph_a": resolved_a.label,
        "graph_b": resolved_b.label,
        "graph_a_session_id": resolved_a.session_id,
        "graph_b_session_id": resolved_b.session_id,
        "shared_object_count": len(shared_ids),
        "only_in_a_count": len(only_in_a),
        "only_in_b_count": len(only_in_b),
        "shared_object_ids": sorted(shared_ids),
        "only_in_a": sorted(only_in_a),
        "only_in_b": sorted(only_in_b),
        "differences": differences,
    }