import cks
from typing import Any
from cks_runtime.runtime import Runtime
from cks_runtime.operations.operation_types import ExplainOperation
from cks_mcp.errors import invalid_json_error

def explain_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Explain either:
    - the current state of an existing session (if session_id is provided), or
    - a freshly parsed JSON structure (fallback compatibility path).
    """
    session_id = arguments.get("session_id")
    if session_id:
        session = runtime.get_session(session_id)
        if not session:
            return {"error": f"Session '{session_id}' not found."}

        # Explain is read-only and must not create a new version in the
        # session's history. begin_transaction/commit_transaction always
        # persists a version regardless of whether anything changed (see
        # ExecutionPipeline.commit), so route through the non-committing
        # executor instead -- the same mechanism merge_branch already uses
        # for its conflict-detection dry-run.
        result = runtime.executor.execute(
            ExplainOperation("explain", knowledge_structure=session.knowledge_structure),
            session,
        )
        return {
            "session_id": session.session_id,
            "explanation": result.payload if result.succeeded else {},
        }

    try:
        structure = cks.parse(arguments["json_data"])
    except cks.SerializationError as exc:
        return invalid_json_error(str(exc))

    session = runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    tx.add_operation(ExplainOperation("explain", knowledge_structure=structure))
    runtime.commit_transaction(tx)
    result = tx.results[0] if tx.results else None
    return result.payload if result else {}