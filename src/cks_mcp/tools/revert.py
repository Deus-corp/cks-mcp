"""
revert: Time-travel operations for session version history.
"""

from typing import Any
from cks_runtime.runtime import Runtime
from cks_runtime.operations.operation_types import ListVersionsOperation, RevertVersionOperation

def list_versions(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return a lightweight list of all versions in the current session."""
    session_id = arguments.get("session_id")
    if not session_id:
        sessions = runtime.list_sessions()
        if not sessions:
            return {"error": "No active sessions found."}
        session = sessions[0]
    else:
        session = runtime.get_session(session_id)
        if not session:
            return {"error": f"Session '{session_id}' not found."}

    op = ListVersionsOperation()
    result = runtime.executor.execute(op, session)
    if result.failed:
        return {"error": str(result.error)}
    return {"versions": result.payload}


def revert_version(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Revert the session to a specific previous version."""
    session_id = arguments.get("session_id")
    target_version_id = arguments.get("target_version_id")

    if not session_id:
        sessions = runtime.list_sessions()
        if not sessions:
            return {"error": "No active sessions found."}
        session = sessions[0]
    else:
        session = runtime.get_session(session_id)
        if not session:
            return {"error": f"Session '{session_id}' not found."}

    if not target_version_id:
        return {"error": "Missing 'target_version_id' parameter."}

    tx = runtime.begin_transaction(session)
    tx.add_operation(RevertVersionOperation("revert", target_version_id=target_version_id))
    version = runtime.commit_transaction(tx)

    return {
        "reverted_to": target_version_id,
        "new_version_id": version.version_id,
        "session_id": session.session_id,
    }