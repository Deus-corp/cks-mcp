"""
query_subgraph: extract a k‑hop neighbourhood from a session's current
Knowledge Structure, with optional budget and filters.

Read‑only – never creates a transaction or version.

``structure_filters`` (optional) is a dict of field → value pairs applied as
an AND-filter on each non-relation object's ``structure`` dict *after* the
subgraph has been extracted by cks-core.  Only objects (not relations) whose
``structure`` contains ALL specified key=value pairs survive; seed objects are
kept regardless of the filter so traversal results are never silently hollow.
Relations are retained whenever both of their participants survive.

Example::

    {
        "structure_filters": {"status": "active", "domain": "biology"}
    }
"""

from __future__ import annotations

from typing import Any

from cks.core import CanonicalRelation, KnowledgeStructure, SubgraphResult
from cks_runtime.operations.operation_types import QuerySubgraphOperation
from cks_runtime.runtime import Runtime

from cks_mcp.errors import missing_parameter, session_not_found


def _make_full_subgraph_result(structure: KnowledgeStructure) -> SubgraphResult:
    """
    Build a ``SubgraphResult`` covering *every* object currently in the
    session, for the ``seed_ids``-omitted ("give me the whole graph") case.

    This intentionally never calls into :class:`QuerySubgraphOperation` /
    ``cks-core``'s BFS traversal, which hard-requires ``seed_ids`` (see
    ``QuerySubgraphOperation.execute``). Rather than loosen that
    requirement in cks-core -- the most regression-sensitive layer in the
    stack -- we just take the session's full object list directly, the same
    data ``serialize_knowledge`` already reads, and wrap it in a
    ``SubgraphResult``-shaped object so the rest of this handler (structure
    filters, compact_mode, budget-reporting fields) can treat it exactly
    like a normal traversal result. No node is truncated here, so the
    budget fields are all "nothing was cut."
    """
    node_count = sum(
        1 for obj in structure.objects if not isinstance(obj, CanonicalRelation)
    )
    return SubgraphResult(
        structure=structure,
        total_found_nodes=node_count,
        returned_nodes=node_count,
        is_truncated=False,
        truncation_reason=None,
        suggested_next_seed=None,
    )


def _apply_structure_filter(
    subgraph_result: Any,
    seed_ids: list[str],
    structure_filters: dict[str, Any],
) -> Any:
    """
    Post-filter the objects in *subgraph_result* by ``structure_filters``.

    Seeds are always kept (regardless of their structure fields) so that the
    traversal anchor is never silently dropped — an empty result from a filter
    mismatch on a seed should be a deliberate query, not a surprise.  Relations
    are kept when every one of their participants survives the filter.

    Returns a mutated-copy ``SubgraphResult``-like dataclass with a fresh
    ``KnowledgeStructure``.  The ``total_found_nodes``,
    ``is_truncated``, ``truncation_reason``, and ``suggested_next_seed``
    fields are carried over unchanged; ``returned_nodes`` is updated to
    reflect the post-filter count.
    """
    from dataclasses import replace

    seed_set = set(seed_ids)

    def _matches(obj: Any) -> bool:
        """True when obj.structure contains all key=value pairs in filters."""
        if isinstance(obj, CanonicalRelation):
            # Relations are governed by participant survival, not field filters.
            return True
        if obj.identity.id in seed_set:
            return True
        for key, expected in structure_filters.items():
            actual = obj.structure.get(key)
            # Coerce to the same primitive type for comparison when possible.
            if isinstance(expected, bool):
                if actual is not expected:
                    return False
            elif isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
                if actual != expected:
                    return False
            else:
                if str(actual) != str(expected):
                    return False
        return True

    surviving_objects = [
        obj
        for obj in subgraph_result.structure.objects
        if not isinstance(obj, CanonicalRelation) and _matches(obj)
    ]
    surviving_ids = {obj.identity.id for obj in surviving_objects}

    surviving_relations = [
        obj
        for obj in subgraph_result.structure.objects
        if isinstance(obj, CanonicalRelation)
        and all(pid in surviving_ids for pid in obj.participants)
    ]

    filtered_structure = KnowledgeStructure(surviving_objects + surviving_relations)
    returned_nodes = len(surviving_objects)

    return replace(
        subgraph_result,
        structure=filtered_structure,
        returned_nodes=returned_nodes,
        is_truncated=(returned_nodes < subgraph_result.total_found_nodes),
    )


async def query_subgraph_tool(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """MCP tool handler for query_subgraph."""
    session_id = arguments.get("session_id")
    if not session_id:
        return missing_parameter("session_id")

    session = runtime.get_session(session_id)
    if not session:
        return session_not_found(session_id)

    seed_ids = arguments.get("seed_ids")

    depth = int(arguments.get("depth", 1))
    compact_mode = arguments.get("compact_mode", False)

    # Optional filters and budget
    include_relation_types = arguments.get("include_relation_types")
    include_object_types = arguments.get("include_object_types")
    max_tokens = arguments.get("max_tokens")
    max_objects = arguments.get("max_objects")
    type_weights = arguments.get("type_weights")

    # Structure-field post-filter (applied after core extraction)
    structure_filters: dict[str, Any] = arguments.get("structure_filters") or {}

    if not seed_ids:
        # No seeds = "give me the whole graph". cks-core's
        # QuerySubgraphOperation requires seed_ids (it's a BFS traversal
        # primitive), so we deliberately bypass it here and build the
        # result straight from the session's current structure instead of
        # loosening that requirement inside cks-core itself.
        subgraph_result = _make_full_subgraph_result(session.knowledge_structure)
    else:
        # Read‑only execution
        op = QuerySubgraphOperation(
            "query_subgraph",
            knowledge_structure=session.knowledge_structure,
            seed_ids=seed_ids,
            depth=depth,
            include_relation_types=include_relation_types,
            include_object_types=include_object_types,
            max_tokens=max_tokens,
            max_objects=max_objects,
            type_weights=type_weights,
            compact_mode=compact_mode,
        )

        result = await runtime.executor.execute(op, session)

        if result.status.value == "failed":
            return {"error": f"query_subgraph failed: {result.error}"}

        subgraph_result = result.payload  # cks-core SubgraphResult

    # Apply structure-field post-filter when requested
    if structure_filters:
        subgraph_result = _apply_structure_filter(
            subgraph_result, seed_ids or [], structure_filters
        )

    if compact_mode:
        from cks.core import CanonicalRelation

        nodes = []
        edges = []
        for obj in subgraph_result.structure.objects:
            if isinstance(obj, CanonicalRelation):
                edges.append(
                    {
                        "source": obj.participants[0]
                        if len(obj.participants) > 0
                        else None,
                        "target": obj.participants[1]
                        if len(obj.participants) > 1
                        else None,
                        "type": obj.relation_type,
                    }
                )
            else:
                nodes.append(
                    {
                        "identity": {
                            "id": obj.identity.id,
                            "type": obj.identity.type,
                            "name": obj.identity.name,
                        },
                        "structure": dict(obj.structure),
                    }
                )

        return {
            "session_id": session_id,
            "subgraph": {"nodes": nodes, "edges": edges},
            "subgraph_root_hash": subgraph_result.structure.root_hash,
            "total_found_nodes": subgraph_result.total_found_nodes,
            "returned_nodes": subgraph_result.returned_nodes,
            "is_truncated": subgraph_result.is_truncated,
            "truncation_reason": subgraph_result.truncation_reason,
            "suggested_next_seed": subgraph_result.suggested_next_seed,
        }

    # Full serialized mode
    subgraph_serialized = runtime.core_bridge.serialize(subgraph_result.structure)

    return {
        "session_id": session_id,
        "subgraph": subgraph_serialized,
        "subgraph_root_hash": subgraph_result.structure.root_hash,
        "total_found_nodes": subgraph_result.total_found_nodes,
        "returned_nodes": subgraph_result.returned_nodes,
        "is_truncated": subgraph_result.is_truncated,
        "truncation_reason": subgraph_result.truncation_reason,
        "suggested_next_seed": subgraph_result.suggested_next_seed,
    }