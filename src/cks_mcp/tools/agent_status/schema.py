"""Input schema definition for the agent_status tool.

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

AGENT_STATUS_SCHEMA = {
    "name": "agent_status",
    "description": "Return the status of a single in-process reasoning sweeper by "
    "'agent_id' (see list_agents for the current set of ids, e.g. "
    "'contradiction', 'inference_staleness', 'provenance_staleness', "
    "'temporal_staleness', 'graph_freshness', 'graph_auto_update', "
    "'graph_health'). Same fields as one entry of list_agents's 'agents' "
    "array. Returns {'agent_id': ..., 'found': false} -- not an error -- "
    "if 'agent_id' doesn't match any currently-enabled sweeper; this "
    "covers both an unrecognized id and a real sweeper name that's "
    "disabled via its Runtime config interval, which this tool cannot "
    "tell apart (a disabled sweeper is never constructed, so it has no "
    "status to report either way). Same process-locality caveat as "
    "list_agents: only in-process sweepers, not the standalone agent "
    "processes (Critic Agent, Enrichment Agent, Fork Resolution Agent, "
    "Pipeline Agent).",
    "inputSchema": {
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "Which sweeper to report on, e.g. 'contradiction'. "
                "See list_agents for the current set of ids.",
            },
        },
        "required": ["agent_id"],
    },
}
