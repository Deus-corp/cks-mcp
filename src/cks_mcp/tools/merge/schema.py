"""Input schema definitions for the merge_knowledge, merge_branch tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

MERGE_KNOWLEDGE_SCHEMA = {
    "name": "merge_knowledge",
    "description": "Three-way merge of Knowledge Structures. Provide a common ancestor "
    "(base) and two independently evolved branches. Returns the merged "
    "structure or a list of conflicts if automatic resolution is impossible.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "json_data_base": {
                "type": "string",
                "description": "The common ancestor Knowledge Structure as a JSON string.",
            },
            "json_data_branch_a": {
                "type": "string",
                "description": "Branch A Knowledge Structure as a JSON string.",
            },
            "json_data_branch_b": {
                "type": "string",
                "description": "Branch B Knowledge Structure as a JSON string.",
            },
            "resolutions": {
                "type": "object",
                "description": "Optional. Per-object conflict resolution strategy. Keys are object IDs. Values: 'branch_a', 'branch_b', null (drop), or a full object definition to override the conflict.",
            },
        },
        "required": ["json_data_base", "json_data_branch_a", "json_data_branch_b"],
    },
}

MERGE_BRANCH_SCHEMA = {
    "name": "merge_branch",
    "description": "Session-aware three-way merge: merge a branch session's changes "
    "into a target session. The merge base is resolved automatically "
    "from the branch's recorded fork point (set by create_branch), so "
    "-- unlike merge_knowledge -- you never supply the base yourself. "
    "On success, commits the merged result as a new version of the "
    "target session. On conflict, returns a 'conflicts' list "
    "(object_id, target_diff, source_diff) instead of merging. Do not "
    "call merge_branch again unchanged after a conflict -- retry it "
    "with a 'resolutions' argument covering each conflicting "
    "object_id (see the 'resolutions' parameter), which merges "
    "everything -- non-conflicting changes and now-resolved conflicts "
    "alike -- in this one call; identities you don't supply a "
    "resolution for are reported again. Only if you'd rather change "
    "the target session's content directly, apply your resolution "
    "there with evolve_knowledge and retry merge_branch with no "
    "resolutions. Either way, close_session the source branch once "
    "it has been fully integrated.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "target_session_id": {
                "type": "string",
                "description": "The session to merge into.",
            },
            "source_session_id": {
                "type": "string",
                "description": "The branch session being merged in.",
            },
            "base_version_id": {
                "type": "string",
                "description": (
                    "Optional. Overrides the merge base with a specific "
                    "version id from the target session's history. Only "
                    "needed if source_session_id wasn't created with "
                    "create_branch's 'version_id' parameter."
                ),
            },
            "resolutions": {
                "type": "object",
                "description": "Optional. Per-object conflict resolution strategies. Keys are object IDs. Values: 'branch_a' (take target's version), 'branch_b' (take source branch's version), null (drop the object), or a complete object definition to use as the merged result.",
            },
        },
        "required": ["target_session_id", "source_session_id"],
    },
}
