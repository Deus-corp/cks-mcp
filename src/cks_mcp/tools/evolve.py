# evolve.py
import cks
from typing import Any
from cks_runtime.runtime import Runtime
from cks_runtime.operations.operation_types import EvolveOperation

def evolve_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    structure = cks.parse(arguments["json_data"])
    operations = arguments.get("operations", [])
    session = runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    tx.add_operation(EvolveOperation("evolve", knowledge_structure=structure, evolution=operations))
    version = runtime.commit_transaction(tx)
    serialized = runtime.core_bridge.serialize(structure)
    return {
        "evolved": True,
        "serialized": serialized,
        "operations_applied": len(operations),
        "version_id": version.version_id,
        "session_id": session.session_id,
    }