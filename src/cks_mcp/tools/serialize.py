import cks
from typing import Any
from cks_runtime.runtime import Runtime
from cks_runtime.operations.operation_types import SerializeOperation
from cks_mcp.errors import invalid_json_error

def serialize_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> Any:
    try:
        structure = cks.parse(arguments["json_data"])
    except cks.SerializationError as exc:
        return invalid_json_error(str(exc))
    session = runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    tx.add_operation(SerializeOperation("serialize", knowledge_structure=structure))
    runtime.commit_transaction(tx)
    result = tx.results[0] if tx.results else None
    return result.payload if result else ""