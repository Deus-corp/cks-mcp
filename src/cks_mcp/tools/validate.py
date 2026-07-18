import cks
from typing import Any
from cks_runtime.runtime import Runtime

def validate_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    structure = cks.parse(arguments["json_data"])
    result = runtime.core_bridge.validate(structure)
    return {
        "valid": result.valid,
        "error_count": result.diagnostic_count if not result.valid else 0,
        "warning_count": 0,
        "information_count": 0,
        "diagnostics": list(result.diagnostics),
        "metadata": dict(result.metadata),
        "message": "Validation successful." if result.valid else "Validation failed.",
    }