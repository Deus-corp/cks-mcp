"""
link_graphs: create a cross-graph relation between an object in graph A
and an object in graph B, written to both source sessions.

Each session only ever gains one new relation object (via
AddRelation/EvolveOperation, the same primitive clone_graph's
target-import path uses) -- existing objects in either graph are left
untouched.
"""

from __future__ import annotations

from typing import Any

import cks
from cks.evolution import AddObject, AddRelation
from cks_runtime.operations.operation_types import EvolveOperation

from cks_mcp import provenance
from cks_mcp.errors import internal_error, missing_parameter
from cks_mcp.graph_resolution import ResolvedGraph, resolve_graph_side


def _serialize_diagnostics(diagnostics: Any) -> list[dict[str, Any]]:
    return [
        {
            "code": d.identity,
            "severity": d.severity.value,
            "message": d.message,
            "location": d.location,
        }
        for d in diagnostics
    ]


async def _write_relation(
    runtime: Any,
    resolved: ResolvedGraph,
    relation: cks.CanonicalRelation,
    *,
    local_participant_id: str,
    remote_participant: cks.KnowledgeObject,
) -> dict[str, Any]:
    """
    Commit `relation` as a new version of `resolved`'s session.

    AddRelation enforces that every participant already exists in the
    *same* structure it's being added to (see cks.evolution.AddRelation)
    -- a cross-graph relation naturally violates this locally, since one
    participant lives in the other graph. To keep the relation
    referentially valid on this side too, a copy of the remote
    participant is added alongside it (skipped if a matching copy is
    already present here, e.g. from a prior link_graphs call between the
    same two graphs). Returns {"version_id": ...} on success, or a
    structured error dict.
    """
    session = resolved.session
    structure = session.knowledge_structure

    evolution: list[Any] = []
    existing_local_copy = structure.get(remote_participant.identity.id)
    if existing_local_copy is None:
        evolution.append(AddObject(remote_participant))
    elif existing_local_copy.structure != remote_participant.structure:
        return {
            "error": "duplicate_object_conflict",
            "message": f"Object '{remote_participant.identity.id}' already exists in "
            f"{resolved.label} with different content than in the other graph -- "
            "object ids must be globally unique across linked graphs.",
        }
    evolution.append(AddRelation(relation))

    op = EvolveOperation("evolve", knowledge_structure=structure, evolution=evolution)
    result = await runtime.executor.execute(op, session, record_metrics=False)
    if result.status.value == "failed":
        return internal_error(f"link_graphs failed writing to {resolved.label}: {result.error}")
    prospective_structure = result.payload

    diags = provenance.verify_structure_provenance(prospective_structure)
    blocking = [d for d in diags if d["severity"] == "error"]
    if blocking:
        return {
            "error": "unverified_provenance",
            "message": f"Cannot link: resulting structure in {resolved.label} contains a "
            "VerificationRecord with invalid or missing provenance.",
            "details": blocking,
        }

    try:
        validation = cks.validate(prospective_structure)
    except Exception as e:
        return {
            "error": "validation_error",
            "message": f"Could not validate {resolved.label} after linking: {e}",
        }
    if not validation.is_valid:
        return {
            "error": "validation_failed",
            "message": f"Linking would produce an invalid structure in {resolved.label}.",
            "diagnostics": _serialize_diagnostics(validation.diagnostics),
        }

    tx = runtime.begin_transaction(session)
    tx.add_operation(op)
    version = await runtime.commit_transaction(tx)
    return {"version_id": version.version_id}


async def link_graphs(runtime: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    object_a_id = arguments.get("object_a_id")
    object_b_id = arguments.get("object_b_id")
    relation_type = arguments.get("relation_type")

    if not object_a_id:
        return missing_parameter("object_a_id")
    if not object_b_id:
        return missing_parameter("object_b_id")
    if not relation_type:
        return missing_parameter("relation_type")

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

    structure_a = resolved_a.session.knowledge_structure
    structure_b = resolved_b.session.knowledge_structure

    if object_a_id not in structure_a:
        return {
            "error": "object_not_found",
            "message": f"Object '{object_a_id}' was not found in graph A ({resolved_a.label}).",
        }
    if object_b_id not in structure_b:
        return {
            "error": "object_not_found",
            "message": f"Object '{object_b_id}' was not found in graph B ({resolved_b.label}).",
        }

    relation_id = (
        f"cross-link:{resolved_a.label}:{object_a_id}:{resolved_b.label}:"
        f"{object_b_id}:{relation_type}"
    )
    if relation_id in structure_a or relation_id in structure_b:
        return {
            "error": "relation_already_exists",
            "message": f"A relation with id '{relation_id}' already exists in one of the "
            "two graphs. link_graphs derives a deterministic id from both object ids and "
            "relation_type, so this link has already been created.",
        }

    relation_name = arguments.get("relation_name") or (
        f"{relation_type}: {object_a_id} -> {object_b_id}"
    )
    relation = cks.CanonicalRelation(
        cks.ObjectIdentity(id=relation_id, type="Relation", name=relation_name),
        participants=[object_a_id, object_b_id],
        relation_type=relation_type,
    )

    result_a = await _write_relation(
        runtime,
        resolved_a,
        relation,
        local_participant_id=object_a_id,
        remote_participant=structure_b.get(object_b_id),
    )
    if "error" in result_a:
        return result_a

    result_b = await _write_relation(
        runtime,
        resolved_b,
        relation,
        local_participant_id=object_b_id,
        remote_participant=structure_a.get(object_a_id),
    )
    if "error" in result_b:
        # Best-effort only: graph A's write already committed above and
        # KnowledgeStructure/session history is append-only, so there is
        # no in-place rollback primitive to reach for here. Surfacing the
        # partial state explicitly (rather than pretending nothing
        # happened) is safer than a silent inconsistency -- the caller
        # can retry link_graphs, since the derived relation_id makes a
        # retry after a partial failure idempotent on the side that
        # already succeeded (the not-yet-written side just proceeds
        # normally, and the already-written side is caught by the
        # relation_already_exists check above on a bare retry -- so a
        # caller should drop graph_a's half from the retry, e.g. by
        # calling evolve_knowledge directly against graph B alone).
        result_b["partial_failure"] = True
        result_b["message"] = (
            f"{result_b.get('message', '')} (graph A / {resolved_a.label} was already "
            "updated successfully before this failure; only graph B / "
            f"{resolved_b.label} failed to write)."
        ).strip()
        return result_b

    return {
        "linked": True,
        "relation_id": relation_id,
        "graph_a_version": result_a["version_id"],
        "graph_b_version": result_b["version_id"],
    }