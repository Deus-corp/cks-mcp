import cks
from typing import Any
from cks_runtime.runtime import Runtime

def serialize_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> str:
    structure = cks.parse(arguments["json_data"])
    return runtime.core_bridge.serialize(structure)