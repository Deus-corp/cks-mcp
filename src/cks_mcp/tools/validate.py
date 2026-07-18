# validate.py
import cks
from typing import Any
from cks_runtime.runtime import Runtime
from cks_runtime.operations.operation_types import ValidateOperation

def validate_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    structure = cks.parse(arguments["json_data"])
    session = runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    tx.add_operation(ValidateOperation("validate", knowledge_structure=structure))
    version = runtime.commit_transaction(tx)
    return {
        "valid": True,  # транзакция не упала – значит валидна
        "version_id": version.version_id,
        "session_id": session.session_id,
        "diagnostics": list(session.diagnostics),
    }