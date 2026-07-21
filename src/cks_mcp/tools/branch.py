"""
branch: create_branch and close_session tools for session management.
"""

from typing import Any
from cks_runtime.runtime import Runtime
from cks_mcp.errors import missing_parameter, session_not_found

def create_branch(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Fork a new session from an existing one, optionally from a specific historical version.
    """
    session_id = arguments.get("session_id")
    if not session_id:
        return missing_parameter("session_id")

    parent = runtime.get_session(session_id)
    if not parent:
        return session_not_found(session_id)

    version_id = arguments.get("version_id")
    try:
        branch = runtime.create_branch(parent, version_id=version_id)
    except ValueError as exc:
        return {"error": "branch_failed", "message": str(exc)}

    return {
        "session_id": branch.session_id,
        "parent_session_id": parent.session_id,
        "parent_version_id": branch.parent_version_id,
        "message": f"Branch session {branch.session_id} created from parent {parent.session_id}.",
    }

def close_session(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Close a session, releasing it from the runtime."""
    session_id = arguments.get("session_id")
    if not session_id:
        return missing_parameter("session_id")

    session = runtime.get_session(session_id)
    if not session:
        return session_not_found(session_id)

    runtime.close_session(session_id)
    return {"session_id": session_id, "closed": True}