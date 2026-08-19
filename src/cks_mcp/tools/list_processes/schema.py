"""Input schema definition for the list_processes tool.

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

LIST_PROCESSES_SCHEMA = {
    "name": "list_processes",
    "description": "Return every known standalone-agent process instance (Critic Agent, "
    "Enrichment Agent, Fork Resolution Agent, Pipeline Agent), most recently "
    "started first, from the shared cks_agent_liveness table (cks-runtime "
    "ADR-014). Each entry has 'instance_id' (uuid4, one per process start -- "
    "a restarted process gets a new entry, the old one stays as history), "
    "'process_kind' ('critic' | 'enrichment' | 'fork_resolution' | "
    "'pipeline'), 'hostname', 'pid', 'liveness_interval_s' (this instance's "
    "own configured heartbeat interval), 'started_at', 'last_heartbeat_at' "
    "(both ISO 8601), 'current_task_id'/'current_task_type' (the outbox "
    "task it's currently working, if any -- best-effort, may lag briefly "
    "behind a crash), and 'status' ('alive' or 'stopped', computed as "
    "last_heartbeat_at within 3x liveness_interval_s -- not stored, so a "
    "slow reader never sees a stale cached verdict). "
    "IMPORTANT: unlike list_agents (which covers only this MCP server's "
    "own in-process sweepers), this reads a table shared across every "
    "process instance that has ever written to this storage backend -- in "
    "a multi-node deployment this can include instances from other nodes, "
    "not just this one.",
    "inputSchema": {
        "type": "object",
        "properties": {},
        "required": [],
        # No accepted parameters -- explicit for strict JSON Schema
        # validators (e.g. Google Gemini function-calling) so an empty
        # object isn't ambiguous with "any object shape allowed".
        "additionalProperties": False,
    },
}