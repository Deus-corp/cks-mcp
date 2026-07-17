import cks
from typing import Any
from cks_runtime.runtime import Runtime

def explain_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    structure = cks.parse(arguments["json_data"])
    return runtime.core_bridge.explain(structure)