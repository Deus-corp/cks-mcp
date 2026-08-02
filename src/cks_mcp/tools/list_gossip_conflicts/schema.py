"""Input schema definition for the list_gossip_conflicts tool.

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

LIST_GOSSIP_CONFLICTS_SCHEMA = {
    "name": "list_gossip_conflicts",
    "description": "Return gossip merge conflicts escalated by a running gossip peer "
    "(CKS_GOSSIP_ENABLED=true) that no one has resolved yet -- the write-side "
    "counterpart to merge_branch's synchronous conflict error, for conflicts "
    "raised by a background gossip cycle instead. Each record has "
    "'session_id' (the target -- pass this as merge_branch's "
    "target_session_id), 'source_session_id' (the remote replica's content, "
    "already registered as a real session here -- pass this as "
    "merge_branch's source_session_id to get back the structured per-object "
    "diff and resolve it; empty if registration failed, meaning only the "
    "conflicting ids below are available), 'source_replica_id', 'conflicts' "
    "(the conflicting object ids), 'detected_at', and 'record_id'. Returns "
    "an empty list if gossip is not enabled or nothing has conflicted. "
    "Records are removed from the queue once returned unless 'peek' is set, "
    "so a Critic agent that lists conflicts is expected to act on (or "
    "re-list with peek=true to keep) what it gets back.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Only return (and drain) conflicts for this session. "
                "Omit to return conflicts for every session.",
            },
            "peek": {
                "type": "boolean",
                "description": "If true, return matching conflicts without removing "
                "them from the queue. Default: false (drain on read).",
                "default": False,
            },
        },
        "required": [],
    },
}
