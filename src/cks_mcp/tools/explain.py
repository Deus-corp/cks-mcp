# explain.py
import cks
from typing import Any
from cks_runtime.runtime import Runtime
from cks_runtime.operations.operation_types import ExplainOperation

def explain_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    structure = cks.parse(arguments["json_data"])
    session = runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    tx.add_operation(ExplainOperation("explain", knowledge_structure=structure))
    version = runtime.commit_transaction(tx)
    explanation = runtime.core_bridge.explain(structure)
    return {
        "object_count": explanation.get("object_count", 0),
        "relation_count": explanation.get("relation_count", 0),
        "summary": explanation.get("summary", {}),
        "version_id": version.version_id,
        "session_id": session.session_id,
    }