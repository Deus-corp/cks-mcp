"""
MCP Resources for CKS – expose sessions and versions as virtual files.

When a client asks for resources/list, the server returns URIs for
every active session, its version history, and each version's
serialized Knowledge Structure.  Reading a resource returns JSON.
"""

from __future__ import annotations

import json
from typing import Any

from cks_runtime.runtime import Runtime
from cks_runtime.session.session import RuntimeSession


def list_resources(runtime: Runtime) -> list[dict[str, Any]]:
    """Return a list of MCP resource descriptors for all active sessions."""
    resources: list[dict[str, Any]] = []

    # Top-level directory
    resources.append({
        "uri": "cks://sessions",
        "name": "CKS Sessions",
        "description": "List of all active CKS session IDs",
        "mimeType": "application/json",
    })

    for session in runtime.sessions.list_sessions():
        sid = session.session_id
        # Session resource
        resources.append({
            "uri": f"cks://sessions/{sid}",
            "name": f"Session {sid[:8]}…",
            "description": f"Knowledge Structure of session {sid}",
            "mimeType": "application/json",
        })
        # Version list resource
        resources.append({
            "uri": f"cks://sessions/{sid}/versions",
            "name": f"Versions of {sid[:8]}…",
            "description": f"Version history of session {sid}",
            "mimeType": "application/json",
        })
        # Individual version resources
        for v in session.version_history:
            resources.append({
                "uri": f"cks://sessions/{sid}/versions/{v.version_id}",
                "name": f"Version {v.version_id[:8]}…",
                "description": f"Snapshot of session {sid} at version {v.version_id}",
                "mimeType": "application/json",
            })

    return resources


def read_resource(runtime: Runtime, uri: str) -> str | None:
    """Return the JSON content for a CKS resource URI, or None if not found."""
    # Helper to serialize a Knowledge Structure
    def serialize_ks(ks):
        try:
            return runtime.core_bridge.serialize(ks)
        except Exception:
            return None

    # Top-level sessions list
    if uri == "cks://sessions":
        session_list = [
            {
                "session_id": s.session_id,
                "created": s.version_history[0].created_at.isoformat() if s.version_history else None,
                "version_count": s.version_count,
            }
            for s in runtime.sessions.list_sessions()
        ]
        return json.dumps(session_list, indent=2, ensure_ascii=False)

    # /sessions/{sid}
    if uri.startswith("cks://sessions/") and uri.count("/") == 2:
        sid = uri.split("/")[-1]
        session = runtime.get_session(sid)
        if session is None:
            return None
        ks_json = serialize_ks(session.knowledge_structure)
        if ks_json is None:
            return json.dumps({"error": "serialization_failed"})
        return ks_json

    # /sessions/{sid}/versions
    if uri.startswith("cks://sessions/") and uri.endswith("/versions"):
        parts = uri.split("/")
        if len(parts) == 4:  # ['cks:', '', 'sessions', '{sid}', 'versions']
            sid = parts[2]
            session = runtime.get_session(sid)
            if session is None:
                return None
            versions_data = [
                {
                    "version_id": v.version_id,
                    "created_at": v.created_at.isoformat(),
                    "transaction_id": v.transaction_id,
                    "metadata": dict(v.metadata),
                }
                for v in session.version_history
            ]
            return json.dumps(versions_data, indent=2, ensure_ascii=False)

    # /sessions/{sid}/versions/{vid}
    if uri.startswith("cks://sessions/") and "/versions/" in uri:
        parts = uri.split("/")
        if len(parts) == 5:  # ['cks:', '', 'sessions', '{sid}', 'versions', '{vid}']
            sid = parts[2]
            vid = parts[4]
            session = runtime.get_session(sid)
            if session is None:
                return None
            try:
                state = session.get_version_state(vid, runtime.core_bridge)
                ks_json = serialize_ks(state)
                if ks_json is None:
                    return json.dumps({"error": "serialization_failed"})
                return ks_json
            except ValueError:
                return None

    return None