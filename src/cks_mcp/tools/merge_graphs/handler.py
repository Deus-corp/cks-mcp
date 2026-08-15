"""
merge_graphs: three-way merge of two registered graphs (or live sessions)
into a brand-new session.

Reuses cks.KnowledgeStructure.merge() directly -- the same core-level
call merge_knowledge uses -- rather than the runtime's session-aware
MergeOperation/merge_branch, since merge_branch's automatic base
resolution depends on a recorded branch fork point (create_branch) that
two independently registered graphs won't generally have. Callers can
still supply an explicit common ancestor via base_graph_name/
base_session_id; without one, an empty structure is used as the base
(see the tool's own schema description for what that implies for
conflict detection).
"""

from __future__ import annotations

from typing import Any

import cks
from cks_runtime.operations.operation_types import EvolveOperation

from cks_mcp import provenance
from cks_mcp.diffing import field_level_diff
from cks_mcp.graph_resolution import ResolvedGraph, resolve_graph_side
from cks_mcp.tools.merge.handler import _parse_resolutions


async def merge_graphs(runtime: Any, arguments: dict[str, Any]) -> dict[str, Any]:
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

    base_structure = None
    if arguments.get("base_session_id") or arguments.get("base_graph_name"):
        resolved_base = await resolve_graph_side(
            runtime, arguments, name_field="base_graph_name", session_field="base_session_id"
        )
        if not isinstance(resolved_base, ResolvedGraph):
            return resolved_base
        base_structure = resolved_base.session.knowledge_structure
    else:
        base_structure = cks.KnowledgeStructure([])

    try:
        resolutions = _parse_resolutions(arguments.get("resolutions"))
    except cks.SerializationError as e:
        return {"error": "invalid_resolutions", "message": f"Invalid 'resolutions' entry: {e}"}

    dropped_relations: list[str] = []
    try:
        merged = base_structure.merge(
            resolved_a.session.knowledge_structure,
            resolved_b.session.knowledge_structure,
            resolutions=resolutions,
            dropped_relations=dropped_relations,
        )
    except Exception as e:
        if hasattr(e, "conflicts"):
            return {
                "merged": False,
                "message": (
                    "Merge conflict detected. For each entry in 'conflicts', "
                    "inspect 'target_diff'/'source_diff' and retry merge_graphs "
                    "with a 'resolutions' argument mapping each object_id to "
                    "'branch_a' (keep graph A's version), 'branch_b' (keep "
                    "graph B's version), null (drop it), or a complete object "
                    "definition."
                ),
                "conflicts": [
                    {
                        "object_id": c.object_id,
                        "target_diff": field_level_diff(c.base, c.branch_a),
                        "source_diff": field_level_diff(c.base, c.branch_b),
                    }
                    for c in e.conflicts
                ],
            }
        return {"error": "merge_failed", "message": str(e)}

    diags = provenance.verify_structure_provenance(merged)
    blocking = [d for d in diags if d["severity"] == "error"]
    if blocking:
        return {
            "merged": False,
            "error": "unverified_provenance",
            "message": "Cannot merge: merged result contains a VerificationRecord "
            "with invalid or missing provenance.",
            "details": blocking,
        }

    new_session = await runtime.create_session(merged)
    seed_op = EvolveOperation("evolve", knowledge_structure=merged, evolution=[])
    tx = runtime.begin_transaction(new_session)
    tx.add_operation(seed_op)
    version = await runtime.commit_transaction(tx)

    response: dict[str, Any] = {
        "merged": True,
        "session_id": new_session.session_id,
        "version_id": version.version_id,
        "graph_a_session_id": resolved_a.session_id,
        "graph_b_session_id": resolved_b.session_id,
        "object_count": len(merged),
    }
    if dropped_relations:
        response["dropped_relations"] = dropped_relations

    register_as = arguments.get("register_as")
    if register_as:
        await runtime.storage.register_graph(
            name=register_as,
            session_id=new_session.session_id,
            description=f"Merge of {resolved_a.label} and {resolved_b.label}.",
            tags="",
            public=False,
            source_graph_name=None,
        )
        response["registered_as"] = register_as

    return response