"""
revert: Time-travel operations for session version history.
"""

from typing import Any
from cks_runtime.runtime import Runtime
from cks_runtime.operations.operation_types import ListVersionsOperation, RevertVersionOperation

def list_versions(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return a lightweight list of all versions in the given session."""
    session_id = arguments.get("session_id")
    if not session_id:
        return {"error": "Missing required parameter: session_id"}

    session = runtime.get_session(session_id)
    if not session:
        return {"error": f"Session '{session_id}' not found."}

    op = ListVersionsOperation()
    result = runtime.executor.execute(op, session)
    if result.failed:
        return {"error": str(result.error)}
    return {
        "session_id": session.session_id,
        "versions": result.payload,
    }


def revert_version(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Revert the session to a specific previous version."""
    session_id = arguments.get("session_id")
    target_version_id = arguments.get("target_version_id")

    if not session_id:
        return {"error": "Missing required parameter: session_id"}
    if not target_version_id:
        return {"error": "Missing required parameter: target_version_id"}

    session = runtime.get_session(session_id)
    if not session:
        return {"error": f"Session '{session_id}' not found."}

    tx = runtime.begin_transaction(session)
    tx.add_operation(RevertVersionOperation("revert", target_version_id=target_version_id))
    version = runtime.commit_transaction(tx)

    return {
        "reverted_to": target_version_id,
        "new_version_id": version.version_id,
        "session_id": session.session_id,
    }