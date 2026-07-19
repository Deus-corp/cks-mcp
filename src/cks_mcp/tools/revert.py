"""
revert: Time-travel operations for session version history.
"""

from typing import Any
from cks_runtime.runtime import Runtime
from cks_runtime.operations.operation_types import RevertVersionOperation

def list_versions(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return a lightweight list of all versions in the given session."""
    session_id = arguments.get("session_id")
    if not session_id:
        return {"error": "Missing required parameter: session_id"}

    session = runtime.get_session(session_id)
    if not session:
        return {"error": f"Session '{session_id}' not found."}

    try:
        versions_data = [
            {
                "version_id": v.version_id,
                "created_at": v.created_at.isoformat(),
                "transaction_id": v.transaction_id,
                "metadata": dict(v.metadata),
            }
            for v in session.version_history
        ]
        return {
            "session_id": session.session_id,
            "versions": versions_data,
        }
    except Exception as e:
        return {"error": f"Internal error in list_versions: {str(e)}"}


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

    try:
        tx = runtime.begin_transaction(session)
        tx.add_operation(RevertVersionOperation("revert", target_version_id=target_version_id))
        version = runtime.commit_transaction(tx)

        serialized = runtime.core_bridge.serialize(session.knowledge_structure)
        return {
            "reverted_to": target_version_id,
            "new_version_id": version.version_id,
            "session_id": session.session_id,
            "serialized": serialized,
        }
    except Exception as e:
        return {"error": f"Revert failed: {str(e)}"}