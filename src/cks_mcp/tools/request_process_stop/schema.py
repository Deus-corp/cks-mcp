"""Input schema definition for the request_process_stop tool.

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

REQUEST_PROCESS_STOP_SCHEMA = {
    "name": "request_process_stop",
    "description": (
        "Request that the most-recently-started instance of a given "
        "standalone-agent process kind stop gracefully. Looks up the "
        "instance the same way process_status does (shared "
        "cks_agent_liveness table, most recent first) and sets its "
        "desired_state='stop_requested' (cks-runtime ADR-016). "
        "Returns {'process_kind': ..., 'instance_id': ..., "
        "'accepted': true} once the request is recorded -- this does "
        "NOT mean the process has stopped yet. Worst-case latency to "
        "actual exit is roughly one liveness_interval (default 30s) "
        "plus however long any in-flight task takes to finish (see "
        "cks-runtime ADR-016's Consequences for the full bound). Call "
        "process_status(process_kind) afterward to confirm the "
        "instance has actually gone -- it reads 'stopped' promptly "
        "once the process exits (ADR-016 §3's immediate-backdate "
        "mechanism), not after a slow TTL wait. "
        "Returns {'process_kind': '<requested>', 'found': false} -- "
        "not an error -- when no instance of that kind has ever been "
        "seen, or the only known instance is already 'stopped' per "
        "the TTL rule (requesting a stop on an already-stopped "
        "instance is a no-op either way, so this tool doesn't "
        "distinguish the two cases, same convention as process_status). "
        "No equivalent 'start' tool exists -- cks-mcp has no mechanism "
        "or privilege to spawn a new OS process (cks-runtime ADR-016 "
        "§4); restarting a stopped agent remains an operational action "
        "outside this tool's scope."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "process_kind": {
                "type": "string",
                "description": (
                    "One of 'critic', 'enrichment', 'fork_resolution', 'pipeline'."
                ),
            },
        },
        "required": ["process_kind"],
    },
}