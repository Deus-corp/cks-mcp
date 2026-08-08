"""
LCA Arbiter: a topology-aware alternative to the purely mechanical
winner-selection policy in ``cks_mcp.fork_resolution_agent``.

Where ``fork_resolution_agent.resolve_fork`` only ever looks at
``VersionVector``/``created_at``/alphabetical tie-breaks (see that
module's docstring), this module additionally looks at *what the two
conflicting objects actually mean* in the session's Knowledge Graph:

1. :func:`find_lca` walks outward (via ``query_subgraph``) from each of
   the two conflicting object ids until their neighborhoods intersect,
   locating their nearest common ancestor in the graph's topology --
   the "least common ancestor" (LCA) of the two forked branches.
2. :func:`extract_delta` pulls out the induced neighborhood between the
   LCA and each branch tip -- what that branch actually changed,
   relative to the shared ancestor.
3. :func:`classify_conflict` compares the two deltas: do they touch
   disjoint parts of the graph (safe to merge automatically), the same
   objects (a genuine arbitration is needed), or does one branch fail
   validation outright (it can simply be dropped)?
4. :func:`resolve_with_lca` ties the above together into a single
   ``LCAResolution`` a caller (e.g. ``ForkResolutionAgent``) can act on,
   including a serialized ``Resolution`` knowledge object suitable for
   recording the decision (and its rationale) back into the graph via
   ``evolve_knowledge``.

Every graph traversal is delegated to the existing ``query_subgraph``
MCP tool (and validation to ``validate_knowledge``) -- this module
never walks ``KnowledgeStructure.objects``/relations by hand. It is a
*policy* layer on top of those tools, not a second implementation of
graph traversal.

.. note::
   ``query_subgraph`` performs *undirected* hyperedge BFS (see
   ``cks.core.KnowledgeStructure.query_subgraph``) -- a Knowledge Graph
   has no built-in "parent"/"child" direction on its relations. The
   "least common ancestor" computed here is therefore the graph-
   theoretic sense of the term for an undirected graph: the node
   nearest (by total hop distance) to both conflicting objects, not a
   DAG-strict ancestor. In practice this is exactly what's wanted for
   fork arbitration: the closest point in the graph both forked
   branches still agree on.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.tools.query_subgraph.handler import query_subgraph_tool
from cks_mcp.tools.validate.handler import validate_knowledge

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# How many extra hops to search for a common ancestor before giving up.
# Each increment issues two more query_subgraph calls (one per branch),
# so this is deliberately modest -- a fork whose branches share no
# ancestor within this radius is treated as having none (find_lca
# returns found=False) rather than searching the whole graph.
_DEFAULT_MAX_SEARCH_DEPTH = 6


# ---------------------------------------------------------------------------
# find_lca
# ---------------------------------------------------------------------------


async def find_lca(
    runtime: Runtime,
    session_id: str,
    object_id_a: str,
    object_id_b: str,
    *,
    max_depth: int = _DEFAULT_MAX_SEARCH_DEPTH,
) -> dict[str, Any]:
    """
    Locate the nearest common ancestor of ``object_id_a`` and
    ``object_id_b`` in session ``session_id``'s current Knowledge Graph.

    Works by calling ``query_subgraph_tool`` with an increasing
    ``depth`` for each of the two seeds (in ``compact_mode``, so only
    node ids are materialized) until their discovered-node sets
    intersect for the first time. The winning candidate is the
    intersecting id with the smallest ``depth_a + depth_b`` (ties
    broken by the smaller max of the two, then alphabetically by id --
    fully deterministic, so every replica arbitrating the same fork
    converges on the same LCA independently).

    Returns ``{"found": True, "lca_id": ..., "depth_a": ..., "depth_b": ...}``
    on success, or ``{"found": False, "reason": "..."}`` if the two
    objects have no common ancestor within ``max_depth`` hops (or
    either seed id doesn't exist in the session at all).
    """
    if object_id_a == object_id_b:
        return {"found": True, "lca_id": object_id_a, "depth_a": 0, "depth_b": 0}

    first_seen_a: dict[str, int] = {}
    first_seen_b: dict[str, int] = {}

    prev_ids_a: set[str] = set()
    prev_ids_b: set[str] = set()
    prev_total_a: int | None = None
    prev_total_b: int | None = None

    for depth in range(max_depth + 1):
        result_a = await query_subgraph_tool(
            runtime,
            {
                "session_id": session_id,
                "seed_ids": [object_id_a],
                "depth": depth,
                "compact_mode": True,
            },
        )
        result_b = await query_subgraph_tool(
            runtime,
            {
                "session_id": session_id,
                "seed_ids": [object_id_b],
                "depth": depth,
                "compact_mode": True,
            },
        )
        if "error" in result_a or "error" in result_b:
            return {
                "found": False,
                "reason": result_a.get("error") or result_b.get("error"),
            }

        ids_a = {n["identity"]["id"] for n in result_a["subgraph"]["nodes"]}
        ids_b = {n["identity"]["id"] for n in result_b["subgraph"]["nodes"]}

        for new_id in ids_a - prev_ids_a:
            first_seen_a.setdefault(new_id, depth)
        for new_id in ids_b - prev_ids_b:
            first_seen_b.setdefault(new_id, depth)

        if depth == 0 and (not ids_a or not ids_b):
            # One of the seed ids doesn't exist in this session at all.
            return {
                "found": False,
                "reason": "object_id_a or object_id_b not found in session",
            }

        common = ids_a & ids_b
        if common:
            best_id = min(
                common,
                key=lambda cid: (
                    first_seen_a[cid] + first_seen_b[cid],
                    max(first_seen_a[cid], first_seen_b[cid]),
                    cid,
                ),
            )
            return {
                "found": True,
                "lca_id": best_id,
                "depth_a": first_seen_a[best_id],
                "depth_b": first_seen_b[best_id],
            }

        total_a = result_a["total_found_nodes"]
        total_b = result_b["total_found_nodes"]
        # Both neighborhoods stopped growing (already fully explored,
        # since no budget was applied) with no intersection -- no
        # amount of extra depth will produce a common ancestor.
        if total_a == prev_total_a and total_b == prev_total_b:
            break
        prev_total_a, prev_total_b = total_a, total_b
        prev_ids_a, prev_ids_b = ids_a, ids_b

    return {"found": False, "reason": f"no common ancestor within {max_depth} hops"}


# ---------------------------------------------------------------------------
# extract_delta
# ---------------------------------------------------------------------------


async def extract_delta(
    runtime: Runtime, session_id: str, lca_id: str, object_id: str
) -> dict[str, Any]:
    """
    Extract the induced neighborhood between ``lca_id`` and
    ``object_id`` -- i.e. what branch ``object_id`` actually changed
    relative to the shared ancestor ``lca_id``.

    Implemented as a single ``query_subgraph`` call seeded on *both*
    ids, with ``depth`` set to the hop distance between them (found via
    a small local BFS-by-depth probe identical in spirit to
    :func:`find_lca`, but seeded on the pair itself so the result is
    the minimal neighborhood connecting them, not each one's full
    ``max_depth`` radius). When ``lca_id == object_id`` (the branch
    made no change beyond the ancestor itself), returns just that one
    node with no relations.

    Returns ``{"nodes": [...], "relations": [...]}`` (compact-mode
    node/edge dicts, see ``query_subgraph_tool``'s ``compact_mode``).
    """
    if lca_id == object_id:
        result = await query_subgraph_tool(
            runtime,
            {
                "session_id": session_id,
                "seed_ids": [object_id],
                "depth": 0,
                "compact_mode": True,
            },
        )
        if "error" in result:
            return {"nodes": [], "relations": [], "error": result["error"]}
        return {"nodes": result["subgraph"]["nodes"], "relations": []}

    # Find the hop distance between lca_id and object_id by probing
    # query_subgraph seeded on lca_id alone with increasing depth,
    # same incremental technique as find_lca.
    distance: int | None = None
    prev_total: int | None = None
    max_probe = _DEFAULT_MAX_SEARCH_DEPTH
    for depth in range(max_probe + 1):
        probe = await query_subgraph_tool(
            runtime,
            {
                "session_id": session_id,
                "seed_ids": [lca_id],
                "depth": depth,
                "compact_mode": True,
            },
        )
        if "error" in probe:
            return {"nodes": [], "relations": [], "error": probe["error"]}
        ids = {n["identity"]["id"] for n in probe["subgraph"]["nodes"]}
        if object_id in ids:
            distance = depth
            break
        total = probe["total_found_nodes"]
        if total == prev_total:
            break
        prev_total = total

    if distance is None:
        # object_id is unreachable from lca_id -- fall back to a
        # single-node delta rather than failing outright, since a
        # caller can still classify/compare on that basis.
        result = await query_subgraph_tool(
            runtime,
            {
                "session_id": session_id,
                "seed_ids": [object_id],
                "depth": 0,
                "compact_mode": True,
            },
        )
        if "error" in result:
            return {"nodes": [], "relations": [], "error": result["error"]}
        return {"nodes": result["subgraph"]["nodes"], "relations": []}

    result = await query_subgraph_tool(
        runtime,
        {
            "session_id": session_id,
            "seed_ids": [lca_id, object_id],
            "depth": max(distance, 1),
            "compact_mode": True,
        },
    )
    if "error" in result:
        return {"nodes": [], "relations": [], "error": result["error"]}

    return {
        "nodes": result["subgraph"]["nodes"],
        "relations": result["subgraph"]["edges"],
    }


# ---------------------------------------------------------------------------
# classify_conflict
# ---------------------------------------------------------------------------


def classify_conflict(delta_a: dict[str, Any], delta_b: dict[str, Any]) -> str:
    """
    Classify a fork given the two branches' deltas (as returned by
    :func:`extract_delta`), *without* looking at validity -- see
    :func:`resolve_with_lca` for the ``"erroneous_branch"`` check,
    which additionally needs a live ``validate_knowledge`` call and so
    can't be done in this synchronous, tool-free function.

    Returns:

    - ``"non_overlapping"`` -- the two deltas' node ids (beyond the
      shared ancestor) are disjoint: each branch changed a different
      part of the graph, so both can be kept via an automatic merge.
    - ``"competing_claims"`` -- the deltas share at least one changed
      node id: both branches touched the same object(s), so a genuine
      arbitration decision is needed.
    """
    ids_a = {n["identity"]["id"] for n in delta_a.get("nodes", [])}
    ids_b = {n["identity"]["id"] for n in delta_b.get("nodes", [])}

    if ids_a & ids_b:
        return "competing_claims"
    return "non_overlapping"


# ---------------------------------------------------------------------------
# Resolution Object construction
# ---------------------------------------------------------------------------


def _resolution_object_id(hash_a: str, hash_b: str, lca_id: str, strategy: str) -> str:
    """Deterministic id: every replica arbitrating the same fork the same way converges on one id."""
    digest = hashlib.sha256(
        f"resolution:{strategy}:{lca_id}:{hash_a}:{hash_b}".encode()
    ).hexdigest()
    return f"resolution-{digest[:16]}"


def _build_resolution_object(
    *,
    object_id_a: str,
    object_id_b: str,
    lca_id: str,
    strategy: str,
    rationale: str,
) -> dict[str, Any]:
    """
    Build the ``Resolution`` knowledge object described in the design
    doc -- a durable, auditable record of an LCA-arbitrated decision,
    suitable for insertion into the graph via ``evolve_knowledge``'s
    ``add_object`` operation.
    """
    branches = sorted([object_id_a, object_id_b])
    resolution_id = _resolution_object_id(branches[0], branches[1], lca_id, strategy)
    return {
        "identity": {
            "id": resolution_id,
            "type": "Resolution",
            "name": f"LCA resolution ({strategy}) for {branches[0]}/{branches[1]}",
        },
        "structure": {
            "strategy_applied": strategy,
            "resolved_branches": branches,
            "common_ancestor": lca_id,
            "rationale": rationale,
            "depends_on": branches,
            "resolved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
    }


# ---------------------------------------------------------------------------
# resolve_with_lca
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class LCAResolution:
    """
    The outcome of :func:`resolve_with_lca`.

    ``resolved`` mirrors ``cks_mcp.agent_loop.Resolution.resolved`` so
    callers built on that pattern (``ForkResolutionAgent``) can adapt
    it directly. ``winner_object_id`` is set whenever the resolution
    implies a single surviving object_id for the CRDT pointer (the
    ``"competing_claims"``/``"erroneous_branch"`` cases); it is
    ``None`` for ``"non_overlapping"``, where *both* branches survive
    and there is no single pointer winner to report (the caller must
    still decide how to represent an automatic merge on the MV-Register
    pointer -- see ``fork_resolution_agent``'s integration notes).
    """

    resolved: bool
    strategy: str | None = None
    lca_id: str | None = None
    winner_object_id: str | None = None
    resolution_object: dict[str, Any] | None = None
    detail: str | None = None
    delta_a: dict[str, Any] = field(default_factory=dict)
    delta_b: dict[str, Any] = field(default_factory=dict)


async def resolve_with_lca(
    runtime: Runtime,
    session_id: str,
    object_id_a: str,
    object_id_b: str,
    *,
    max_depth: int = _DEFAULT_MAX_SEARCH_DEPTH,
) -> LCAResolution:
    """
    Full LCA-arbitration pipeline for one pair of conflicting object
    ids: find their common ancestor, extract each branch's delta,
    classify the conflict, and build a resolution.

    - ``"non_overlapping"`` -> both branches are kept (a merge
      resolution); ``winner_object_id`` is left ``None``.
    - one branch fails ``validate_knowledge`` and the other doesn't ->
      reclassified as ``"erroneous_branch"``; the valid branch wins and
      the invalid one is marked ``deprecated`` in its resolution
      object's rationale.
    - otherwise, ``"competing_claims"`` -> a Resolution Object is built
      with ``depends_on`` on both branches and no single winner is
      picked here (that's a genuine arbitration call this module
      deliberately leaves to a human/Critic agent reviewing the
      Resolution Object -- ``winner_object_id`` is left ``None`` and
      ``resolved`` is ``True`` since *recording* the arbitration need
      is itself the resolution this function is responsible for).

    Never raises for graph-shaped reasons (no LCA found, tool errors)
    -- returns ``LCAResolution(resolved=False, detail=...)`` instead,
    so a caller can cleanly fall back to a different policy.
    """
    lca_result = await find_lca(
        runtime, session_id, object_id_a, object_id_b, max_depth=max_depth
    )
    if not lca_result.get("found"):
        return LCAResolution(
            resolved=False,
            detail=f"find_lca: {lca_result.get('reason', 'no common ancestor found')}",
        )

    lca_id = lca_result["lca_id"]

    delta_a = await extract_delta(runtime, session_id, lca_id, object_id_a)
    delta_b = await extract_delta(runtime, session_id, lca_id, object_id_b)
    if "error" in delta_a or "error" in delta_b:
        return LCAResolution(
            resolved=False,
            lca_id=lca_id,
            detail=f"extract_delta failed: {delta_a.get('error') or delta_b.get('error')}",
            delta_a=delta_a,
            delta_b=delta_b,
        )

    strategy = classify_conflict(delta_a, delta_b)

    # erroneous_branch check: only meaningful (and only worth the two
    # extra validate_knowledge calls) when the branches actually
    # contend for the same object(s) -- a non_overlapping merge never
    # needs it, since both branches are being kept regardless.
    winner_object_id: str | None = None
    if strategy == "competing_claims":
        valid_a = await _branch_is_valid(runtime, session_id, delta_a)
        valid_b = await _branch_is_valid(runtime, session_id, delta_b)
        if valid_a and not valid_b:
            strategy = "erroneous_branch"
            winner_object_id = object_id_a
        elif valid_b and not valid_a:
            strategy = "erroneous_branch"
            winner_object_id = object_id_b

    if strategy == "non_overlapping":
        rationale = (
            f"Branches {object_id_a!r} and {object_id_b!r} diverge from common "
            f"ancestor {lca_id!r} in disjoint parts of the graph "
            f"(depth_a={lca_result['depth_a']}, depth_b={lca_result['depth_b']}); "
            "both are retained via merge."
        )
    elif strategy == "erroneous_branch":
        loser = object_id_b if winner_object_id == object_id_a else object_id_a
        rationale = (
            f"Branch {loser!r} failed validate_knowledge and is deprecated in "
            f"favor of {winner_object_id!r}, both diverging from common "
            f"ancestor {lca_id!r}."
        )
    else:  # competing_claims
        rationale = (
            f"Branches {object_id_a!r} and {object_id_b!r} both modify overlapping "
            f"parts of the graph relative to common ancestor {lca_id!r} "
            f"(depth_a={lca_result['depth_a']}, depth_b={lca_result['depth_b']}); "
            "requires arbitration -- see depends_on."
        )

    resolution_object = _build_resolution_object(
        object_id_a=object_id_a,
        object_id_b=object_id_b,
        lca_id=lca_id,
        strategy=strategy,
        rationale=rationale,
    )

    return LCAResolution(
        resolved=True,
        strategy=strategy,
        lca_id=lca_id,
        winner_object_id=winner_object_id,
        resolution_object=resolution_object,
        detail=rationale,
        delta_a=delta_a,
        delta_b=delta_b,
    )


async def _branch_is_valid(
    runtime: Runtime, session_id: str, delta: dict[str, Any]
) -> bool:
    """
    Check whether a branch's delta is internally consistent, via
    ``validate_knowledge`` on a freshly-parsed structure built from the
    delta's own nodes/relations (compact-mode dicts -> CKS json_data).
    Never raises; a malformed delta or a validate_knowledge error is
    treated as invalid (conservative: an unreadable branch can't be
    trusted as the winner).
    """
    objects = [
        {
            "identity": dict(n["identity"]),
            "structure": n.get("structure", {}),
        }
        for n in delta.get("nodes", [])
    ]
    relations = [
        {
            "identity": {
                "id": f"{e['source']}-{e['target']}-{e['type']}",
                "type": "Relation",
                "name": e["type"] or "relation",
            },
            "structure": {
                "participants": [e["source"], e["target"]],
                "relation_type": e["type"],
            },
        }
        for e in delta.get("relations", [])
        if e.get("source") and e.get("target")
    ]
    json_data = json.dumps({"objects": objects + relations})

    try:
        result = await validate_knowledge(runtime, {"json_data": json_data})
    except Exception:  # noqa: BLE001 -- never let a validation probe crash arbitration
        return False
    if "error" in result:
        return False
    return bool(result.get("valid"))