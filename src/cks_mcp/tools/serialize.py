# serialize.py
import cks
from typing import Any
from cks_runtime.runtime import Runtime
from cks_runtime.operations.operation_types import SerializeOperation

def serialize_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> str:
    structure = cks.parse(arguments["json_data"])
    session = runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    tx.add_operation(SerializeOperation("serialize", knowledge_structure=structure))
    runtime.commit_transaction(tx)
    return runtime.core_bridge.serialize(structure)