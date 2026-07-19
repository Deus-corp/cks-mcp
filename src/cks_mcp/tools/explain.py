import cks
from typing import Any
from cks_runtime.runtime import Runtime
from cks_runtime.operations.operation_types import ExplainOperation

def explain_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    structure = cks.parse(arguments["json_data"])
    session = runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    tx.add_operation(ExplainOperation("explain", knowledge_structure=structure))
    runtime.commit_transaction(tx)
    result = tx.results[0] if tx.results else None
    return result.payload if result else {}