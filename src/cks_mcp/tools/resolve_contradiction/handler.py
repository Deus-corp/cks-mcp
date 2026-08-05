"""
resolve_contradiction: resolve a ``contradiction_detected`` task
(``ContradictionSweeper``, cks-runtime) -- a ``MutualExclusionRule``/
``FunctionalRelationRule`` violation surfaced by cks-core's opt-in
``mutual_exclusion``/``functional_relation`` extension constraints (see
``cks/constraints/contradiction.py``).

Where does this sit relative to the other conflict-resolution tools
=====================================================================
Like ``refresh_verification``, this is a **mechanical** tool: no LLM,
no ``auto_resolve`` path. Unlike an expired ``valid_until``
(``resolve_temporal_conflict``), which genuinely has no single correct
remedy, a contradiction between two relations has exactly one
structurally-sound fix -- remove one of the two (or more) conflicting
relations so the pair/group is no longer jointly asserted. Which one
to remove is not a domain judgment this tool tries to make well; it
applies a simple, deterministic heuristic (drop the relation whose id
sorts first alphabetically among the conflicting set) so the same
contradiction always resolves the same way. A future ``auto_resolve``
(LLM) path could pick more thoughtfully (e.g. keep the relation with
higher-confidence provenance) -- see the module's own TODO note below
-- but that is not this tool's job today.

Two modes
---------
- No ``contradiction_ids``: read-only, like ``detect_contradictions`` --
  returns every currently-live contradiction in the session, each
  carrying a stable ``id`` (the same value ``detect_contradictions``
  reports as a diagnostic's ``location``) plus the raw ``relation_ids``
  that participate in it, so a caller can choose which ones to pass
  back in a follow-up call.
- ``contradiction_ids`` given: for each one, recomputes the current
  contradiction set (a contradiction may have already been resolved by
  an earlier call in the same batch, or by unrelated concurrent
  activity, since the last detection) and, if still present, builds a
  ``remove_relation`` operation for the alphabetically-first relation
  id in that contradiction's ``relation_ids``. An id that no longer
  matches any live contradiction is reported as an error for that item
  rather than silently skipped. Pass ``commit: true`` to apply the
  combined operations via ``evolve_knowledge`` immediately; otherwise
  the operations are returned for the caller to apply itself.

TODO(auto_resolve): a smarter, LLM-assisted resolution path (picking
which relation to keep based on provenance/confidence/recency) could
be added later, following the same ``auto_resolve`` pattern
``arbitrate_inference_conflict``/``resolve_gossip_conflict`` already
use -- deliberately out of scope for this first, mechanical version.
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.errors import missing_parameter, session_not_found
from cks_mcp.tools.evolve.handler import evolve_knowledge

# Contradiction extension constraint identities this tool resolves.
# Deliberately not CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT (WARNING
# severity, a resolvable belief conflict handled by
# arbitrate_inference_conflict instead -- see detect_contradictions'
# own docstring for why it's a different kind of finding).
_MUTUAL_EXCLUSION_IDENTITY = "CKS-EXT-MUTUAL-EXCLUSION"
_FUNCTIONAL_RELATION_IDENTITY = "CKS-EXT-FUNCTIONAL-RELATION"

_MUTUAL_EXCLUSION_RULE_TYPE = "MutualExclusionRule"
_FUNCTIONAL_RELATION_RULE_TYPE = "FunctionalRelationRule"


def _find_contradictions(structure: Any) -> list[dict[str, Any]]:
    """
    Recompute every live contradiction directly from ``structure``,
    mirroring cks-core's ``MutualExclusionConstraint``/
    ``FunctionalRelationConstraint.evaluate()`` (see
    ``cks/constraints/contradiction.py``) -- but returning each
    violation's own participating relation ids alongside its
    diagnostic-shaped fields, since ``detect_contradictions``'
    free-text ``message`` does not expose those in a structured,
    parseable way and this tool needs them to decide what to remove.

    Each returned dict's ``id`` is exactly the value
    ``detect_contradictions`` reports as that diagnostic's
    ``location`` -- the two tools' outputs are meant to be used
    together (detect to find contradiction ids, resolve to fix them).
    """
    contradictions: list[dict[str, Any]] = []

    # --- mutual_exclusion ---
    pairs: set[tuple[str, str]] = set()
    for obj in structure.objects:
        if obj.identity.type != _MUTUAL_EXCLUSION_RULE_TYPE:
            continue
        type_a = obj.structure.get("relation_type_a")
        type_b = obj.structure.get("relation_type_b")
        if not type_a or not type_b or type_a == type_b:
            continue
        pairs.add(tuple(sorted((type_a, type_b))))

    if pairs:
        by_relation_type: dict[str, dict[tuple[str, str], str]] = {}
        for relation in structure.relations():
            if len(relation.participants) != 2:
                continue
            source_id, target_id = relation.participants
            by_relation_type.setdefault(relation.relation_type, {})[
                (source_id, target_id)
            ] = relation.identity.id

        for type_a, type_b in sorted(pairs):
            map_a = by_relation_type.get(type_a, {})
            map_b = by_relation_type.get(type_b, {})
            for participants in sorted(set(map_a) & set(map_b)):
                source_id, target_id = participants
                relation_a_id = map_a[participants]
                relation_b_id = map_b[participants]
                contradictions.append(
                    {
                        "id": relation_a_id,
                        "code": _MUTUAL_EXCLUSION_IDENTITY,
                        "severity": "error",
                        "message": (
                            f"Relation '{relation_a_id}' (type '{type_a}') "
                            f"and relation '{relation_b_id}' (type "
                            f"'{type_b}') both connect '{source_id}' to "
                            f"'{target_id}', but a MutualExclusionRule "
                            f"declares these relation_types mutually "
                            f"exclusive."
                        ),
                        "relation_ids": sorted((relation_a_id, relation_b_id)),
                    }
                )

    # --- functional_relation ---
    functional_types: set[str] = set()
    for obj in structure.objects:
        if obj.identity.type != _FUNCTIONAL_RELATION_RULE_TYPE:
            continue
        relation_type = obj.structure.get("relation_type")
        if relation_type:
            functional_types.add(relation_type)

    if functional_types:
        targets_by_source: dict[str, dict[str, dict[str, str]]] = {}
        for relation in structure.relations():
            if relation.relation_type not in functional_types:
                continue
            if len(relation.participants) != 2:
                continue
            source_id, target_id = relation.participants
            bucket = targets_by_source.setdefault(
                relation.relation_type, {}
            ).setdefault(source_id, {})
            bucket[target_id] = relation.identity.id

        for relation_type in sorted(targets_by_source):
            sources = targets_by_source[relation_type]
            for source_id in sorted(sources):
                targets = sources[source_id]
                if len(targets) <= 1:
                    continue
                target_ids = sorted(targets)
                relation_ids = sorted(targets.values())
                first_relation_id = relation_ids[0]
                contradictions.append(
                    {
                        "id": first_relation_id,
                        "code": _FUNCTIONAL_RELATION_IDENTITY,
                        "severity": "error",
                        "message": (
                            f"Source '{source_id}' has {len(targets)} "
                            f"distinct targets via functional relation_type "
                            f"'{relation_type}': {target_ids}. A "
                            f"FunctionalRelationRule declares this "
                            f"relation_type single-valued per source."
                        ),
                        "relation_ids": relation_ids,
                    }
                )

    return contradictions


async def resolve_contradiction(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    session_id = arguments.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return missing_parameter("session_id")

    session = runtime.get_session(session_id)
    if session is None:
        return session_not_found(session_id)

    structure = session.knowledge_structure
    contradictions = _find_contradictions(structure) if structure is not None else []

    contradiction_ids = arguments.get("contradiction_ids")

    if not contradiction_ids:
        # Read-only path: same shape as detect_contradictions, plus the
        # raw relation_ids a follow-up call would need.
        return {
            "session_id": session_id,
            "contradiction_count": len(contradictions),
            "contradictions": contradictions,
        }

    if not isinstance(contradiction_ids, list):
        return {
            "error": "invalid_parameter",
            "message": "'contradiction_ids' must be a list of strings.",
        }

    by_id = {c["id"]: c for c in contradictions}

    operations: list[dict[str, Any]] = []
    removed_relation_ids: set[str] = set()
    results: list[dict[str, Any]] = []

    for contradiction_id in contradiction_ids:
        contradiction = by_id.get(contradiction_id)
        if contradiction is None:
            results.append(
                {
                    "contradiction_id": contradiction_id,
                    "error": "contradiction_not_found",
                    "message": (
                        f"Contradiction '{contradiction_id}' was not found "
                        f"in session '{session_id}' -- it may have already "
                        "been resolved by an earlier resolution, or the id "
                        "does not match any current violation's location."
                    ),
                }
            )
            continue

        # Heuristic: drop the alphabetically-first relation id among the
        # conflicting set. relation_ids is already sorted (see
        # _find_contradictions).
        relation_id_to_remove = contradiction["relation_ids"][0]

        results.append(
            {
                "contradiction_id": contradiction_id,
                "code": contradiction["code"],
                "removed_relation_id": relation_id_to_remove,
            }
        )

        if relation_id_to_remove not in removed_relation_ids:
            removed_relation_ids.add(relation_id_to_remove)
            operations.append(
                {"type": "remove_relation", "relation_id": relation_id_to_remove}
            )

    response: dict[str, Any] = {
        "session_id": session_id,
        "results": results,
        "operations": operations,
    }

    if arguments.get("commit") and operations:
        evolve_result = await evolve_knowledge(
            runtime,
            {
                "session_id": session_id,
                "operations": operations,
                "extensions": ["mutual_exclusion", "functional_relation"],
            },
        )
        response["commit_result"] = evolve_result

    return response
