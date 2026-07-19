import cks
from cks.evolution import parse_operations
from typing import Any
from cks_runtime.runtime import Runtime
from cks_runtime.operations.operation_types import EvolveOperation
from cks_mcp.errors import invalid_json_error

def evolve_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        structure = cks.parse(arguments["json_data"])
    except cks.SerializationError as exc:
        return invalid_json_error(str(exc))

    try:
        operations = parse_operations(arguments.get("operations", []))
    except ValueError as exc:
        return {
            "error": "invalid_operations",
            "message": f"Could not parse 'operations': {exc}",
        }

    session_id = arguments.get("session_id")
    if session_id:
        session = runtime.get_session(session_id)
        if not session:
            return {"error": f"Session '{session_id}' not found."}
    else:
        session = runtime.create_session(structure)

    tx = runtime.begin_transaction(session)
    tx.add_operation(EvolveOperation("evolve", knowledge_structure=structure, evolution=operations))
    version = runtime.commit_transaction(tx)
    serialized = runtime.core_bridge.serialize(session.knowledge_structure)
    return {
        "evolved": True,
        "serialized": serialized,
        "operations_applied": len(operations),
        "version_id": version.version_id,
        "session_id": session.session_id,
    }