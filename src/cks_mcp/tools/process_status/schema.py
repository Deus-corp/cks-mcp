"""Input schema definition for the process_status tool.

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

PROCESS_STATUS_SCHEMA = {
    "name": "process_status",
    "description": (
        "Return the status of the most-recently-started instance "
        "of a given standalone-agent process kind. "
        "Uses the shared cks_agent_liveness table (cks-runtime ADR-014). "
        "Returns the same fields as a single entry from list_processes "
        "(instance_id, process_kind, hostname, pid, "
        "liveness_interval_s, started_at, last_heartbeat_at, "
        "current_task_id, current_task_type, status). "
        "Returns {'process_kind': '<requested>', 'found': false} "
        "when the process kind has never been seen (or hasn't been seen "
        "since the storage backend was last wiped). "
        "IMPORTANT: like list_processes, this reads a table shared across "
        "every process instance — in a multi‑node deployment it may return "
        "data from a different node."
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