import cks
from typing import Any
from cks_runtime.runtime import Runtime

def explain_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    structure = cks.parse(arguments["json_data"])
    explanation = runtime.core_bridge.explain(structure)
    return {
        "object_count": explanation.get("object_count", 0),
        "relation_count": explanation.get("relation_count", 0),
        "summary": explanation.get("summary", {}),
        "raw": explanation,
    }