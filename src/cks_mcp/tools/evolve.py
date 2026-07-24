import cks
from cks.evolution import parse_operations
from typing import Any
from cks_runtime.runtime import Runtime
from cks_runtime.operations.operation_types import EvolveOperation
from cks_runtime.session.session import RuntimeSession
from cks_mcp.errors import invalid_json_error
from cks_mcp import provenance

def evolve_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    session_id = arguments.get("session_id")
    session_existed = bool(session_id)
    if session_id:
        session = runtime.get_session(session_id)
        if not session:
            return {"error": f"Session '{session_id}' not found."}
        structure = session.knowledge_structure
    else:
        try:
            structure = cks.parse(arguments["json_data"])
        except cks.SerializationError as exc:
            return invalid_json_error(str(exc))
        # Same reasoning as validate_knowledge: don't persist a
        # session for content that might still be rejected by the
        # provenance check below. Use a throwaway, unregistered
        # session for the dry-run.
        session = RuntimeSession(knowledge_structure=structure)

    try:
        operations = parse_operations(arguments.get("operations", []))
    except ValueError as exc:
        return {
            "error": "invalid_operations",
            "message": f"Could not parse 'operations': {exc}",
        }

    if not operations:
        return {
            "error": "no_operations",
            "message": "No evolution operations were provided.",
        }

    # Dry-run to check provenance before committing
    op = EvolveOperation("evolve", knowledge_structure=structure, evolution=operations)
    result = runtime.executor.execute(op, session)
    if result.status.value == "failed":
        return {"error": f"Evolution failed: {result.error}"}
    prospective_structure = result.payload

    # Verify provenance of the prospective new state. Only an
    # 'error'-severity diagnostic (forged/tampered signature, or an
    # ambiguous verified_by target) blocks the commit -- a 'warning'
    # (e.g. CKS-MCP-UNLINKED-VERIFICATION-RECORD, a genuinely-signed
    # record whose verified_by relation hasn't been added in *this*
    # call) must not, or a legitimate record added and linked across
    # two separate evolve_knowledge calls could never succeed.
    diags = provenance.verify_structure_provenance(prospective_structure)
    blocking = [d for d in diags if d["severity"] == "error"]
    if blocking:
        return {
            "error": "validation_failed",
            "message": "Cannot commit evolution: VerificationRecord has invalid or missing provenance signature.",
            "details": blocking,
        }

    # Validate the evolved structure before committing
    try:
        validation = cks.validate(prospective_structure)
    except Exception as e:
        return {
            "error": "validation_error",
            "message": f"Could not validate evolved structure: {e}",
        }
    if not validation.is_valid:
        return {
            "error": "validation_failed",
            "message": "Evolution would produce an invalid structure.",
            "diagnostics": [
                {
                    "code": d.identity,
                    "severity": d.severity.value,
                    "message": d.message,
                    "location": d.location,
                }
                for d in validation.diagnostics
            ],
        }

    if not session_existed:
        session = runtime.create_session(structure)

    tx = runtime.begin_transaction(session)
    tx.add_operation(op)
    version = runtime.commit_transaction(tx)

    # Detect cascade-deleted relations caused by RemoveObject operations
    cascade_removed: list[str] = []
    for op in operations:
        if hasattr(op, '_object_id'):
            removed_id = op._object_id
            for rel in structure.relations():
                if removed_id in rel.participants:
                    # Check if this relation no longer exists in the evolved state
                    if rel.identity.id not in {
                        r.identity.id for r in session.knowledge_structure.relations()
                    }:
                        cascade_removed.append(rel.identity.id)

    serialized = runtime.core_bridge.serialize(session.knowledge_structure)
    response = {
        "evolved": True,
        "serialized": serialized,
        "operations_applied": len(operations),
        "version_id": version.version_id,
        "session_id": session.session_id,
    }
    if cascade_removed:
        response["cascade_removed_relations"] = cascade_removed
    return response
