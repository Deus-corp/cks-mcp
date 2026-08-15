"""
clone_graph: copy an existing registered graph (or any live session) into
a new session -- or merge it into an existing one -- without ever
modifying the source.

Two source-resolution paths are supported (source_session_id takes
precedence when both are given):

  - ``source_session_id`` -- clone directly from a live session.
  - ``graph_name`` -- resolve via the graph registry (register_graph)
    first, then clone the session it points at.

And two destinations:

  - No ``target_session_id`` -- create a brand-new session seeded with
    a full copy of the source's Knowledge Structure, committed as that
    new session's first version.
  - ``target_session_id`` -- import only the objects/relations from the
    source that the target doesn't already have (by identity id), via
    an ``EvolveOperation`` of ``AddObject``/``AddRelation`` steps,
    committed as a new version on the target session. Existing objects
    in the target are left untouched.

Either way the source session's own state is only ever read, never
mutated -- ``KnowledgeStructure`` is immutable, so simply reusing
``source_session.knowledge_structure`` as-is cannot affect the source.
"""

from __future__ import annotations

from typing import Any

import cks
from cks.evolution import AddObject, AddRelation, CanonicalRelation
from cks_runtime.operations.operation_types import EvolveOperation
from cks_runtime.runtime import Runtime

from cks_mcp import provenance
from cks_mcp.errors import (
    graph_not_found,
    internal_error,
    missing_parameter,
    session_not_found,
)


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


async def _resolve_source(
    runtime: Runtime, arguments: dict[str, Any]
) -> tuple[Any, str, str | None] | dict[str, Any]:
    """
    Returns ``(source_session, source_session_id, source_graph_name)`` on
    success, or a structured error dict on failure.
    """
    source_session_id = arguments.get("source_session_id")
    graph_name = arguments.get("graph_name")

    if not source_session_id and not graph_name:
        return missing_parameter("graph_name (or source_session_id)")

    source_graph_name: str | None = None
    if not source_session_id:
        assert graph_name is not None  # guaranteed by the check above
        record = await runtime.storage.get_graph(graph_name)
        if record is None:
            return graph_not_found(graph_name)
        source_session_id = record["session_id"]
        source_graph_name = graph_name

    source_session = runtime.get_session(source_session_id)
    if source_session is None:
        return session_not_found(source_session_id)

    return source_session, source_session_id, source_graph_name


async def clone_graph(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    resolved = await _resolve_source(runtime, arguments)
    if isinstance(resolved, dict):
        return resolved
    source_session, source_session_id, source_graph_name = resolved

    source_structure = source_session.knowledge_structure
    target_session_id = arguments.get("target_session_id")

    if target_session_id:
        # Existence + open-ness already verified by the
        # require_open_session("target_session_id") middleware wrapping
        # this handler in registry.py.
        target_session = runtime.get_session(target_session_id)
        target_structure = target_session.knowledge_structure

        add_ops: list[Any] = []
        for obj in source_structure.objects:
            if obj.identity.id in target_structure:
                continue
            if isinstance(obj, CanonicalRelation):
                add_ops.append(AddRelation(obj))
            else:
                add_ops.append(AddObject(obj))

        imported_objects = sum(1 for op in add_ops if isinstance(op, AddObject))
        imported_relations = sum(1 for op in add_ops if isinstance(op, AddRelation))

        response: dict[str, Any] = {
            "session_id": target_session.session_id,
            "source_session_id": source_session_id,
            "imported_objects": imported_objects,
            "imported_relations": imported_relations,
        }
        if source_graph_name:
            response["source_graph_name"] = source_graph_name

        if not add_ops:
            response["version_id"] = None
            response["message"] = (
                "Target session already contains every object/relation "
                "from the source graph; nothing to import."
            )
            return response

        op = EvolveOperation("evolve", knowledge_structure=target_structure, evolution=add_ops)
        result = await runtime.executor.execute(op, target_session, record_metrics=False)
        if result.status.value == "failed":
            return internal_error(f"Clone import failed: {result.error}")
        prospective_structure = result.payload

        diags = provenance.verify_structure_provenance(prospective_structure)
        blocking = [d for d in diags if d["severity"] == "error"]
        if blocking:
            return {
                "error": "unverified_provenance",
                "message": (
                    "Cannot clone: source graph contains a VerificationRecord "
                    "with an invalid or missing provenance signature."
                ),
                "details": blocking,
            }

        try:
            validation = cks.validate(prospective_structure)
        except Exception as e:
            return {
                "error": "validation_error",
                "message": f"Could not validate cloned structure: {e}",
            }
        if not validation.is_valid:
            return {
                "error": "validation_failed",
                "message": "Cloning would produce an invalid structure in the target session.",
                "diagnostics": _serialize_diagnostics(validation.diagnostics),
            }

        tx = runtime.begin_transaction(target_session)
        tx.add_operation(op)
        version = await runtime.commit_transaction(tx)

        response["version_id"] = version.version_id
        return response

    # No target_session_id: clone into a brand-new session. The source
    # structure is reused as-is (immutable, so this cannot mutate the
    # source) and committed as the new session's first version via a
    # no-op EvolveOperation -- same "new session" pattern evolve_knowledge
    # uses when called without an existing session_id.
    new_session = await runtime.create_session(source_structure)
    seed_op = EvolveOperation("evolve", knowledge_structure=source_structure, evolution=[])
    tx = runtime.begin_transaction(new_session)
    tx.add_operation(seed_op)
    version = await runtime.commit_transaction(tx)

    imported_relations = len(source_structure.relations())
    imported_objects = len(source_structure.objects) - imported_relations

    response = {
        "session_id": new_session.session_id,
        "version_id": version.version_id,
        "source_session_id": source_session_id,
        "imported_objects": imported_objects,
        "imported_relations": imported_relations,
    }
    if source_graph_name:
        response["source_graph_name"] = source_graph_name

    copy_name = arguments.get("copy_name")
    if copy_name:
        description = arguments.get("description") or (
            f"Clone of {source_graph_name or source_session_id}."
        )
        await runtime.storage.register_graph(
            name=copy_name,
            session_id=new_session.session_id,
            description=description,
            tags=arguments.get("tags") or "",
            public=bool(arguments.get("public", False)),
        )
        response["registered_as"] = copy_name

    return response
