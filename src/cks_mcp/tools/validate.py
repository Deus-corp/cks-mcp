import cks
from typing import Any
from cks_runtime.runtime import Runtime

def validate_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    structure = cks.parse(arguments["json_data"])
    result = runtime.core_bridge.validate(structure)
    return {
        "valid": result.valid,
        "diagnostics": list(result.diagnostics),
        "metadata": dict(result.metadata),
    }