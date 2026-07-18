import cks
from typing import Any
from cks_runtime.runtime import Runtime

def evolve_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    structure = cks.parse(arguments["json_data"])
    operations = arguments.get("operations", [])
    evolved = runtime.core_bridge.evolve(structure, operations)
    serialized = runtime.core_bridge.serialize(evolved)
    return {
        "evolved": True,
        "serialized": serialized,
        "operations_applied": len(operations),
    }