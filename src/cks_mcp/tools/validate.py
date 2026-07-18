import cks
from typing import Any
from cks_runtime.diagnostics.diagnostic import DiagnosticSeverity
from cks_runtime.runtime import Runtime
from cks_runtime.operations.operation_types import ValidateOperation


def _serialize_diagnostic(diagnostic: Any) -> dict[str, Any]:
    return {
        "code": diagnostic.code,
        "severity": diagnostic.severity.value,
        "source": diagnostic.source.value,
        "message": diagnostic.message,
        "metadata": dict(diagnostic.metadata),
    }


def validate_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    structure = cks.parse(arguments["json_data"])
    session = runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    tx.add_operation(ValidateOperation("validate", knowledge_structure=structure))
    version = runtime.commit_transaction(tx)

    diagnostics = list(session.diagnostics)
    valid = not any(d.severity is DiagnosticSeverity.ERROR for d in diagnostics)

    return {
        "valid": valid,
        "version_id": version.version_id,
        "session_id": session.session_id,
        "diagnostics": [_serialize_diagnostic(d) for d in diagnostics],
    }