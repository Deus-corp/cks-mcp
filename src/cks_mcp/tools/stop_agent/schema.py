"""Input schema definition for the stop_agent tool.

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

STOP_AGENT_SCHEMA = {
    "name": "stop_agent",
    "description": "Stop a single in-process reasoning sweeper by 'agent_id' (see "
    "list_agents for the current set of ids, e.g. 'contradiction', "
    "'inference_staleness', 'provenance_staleness', 'temporal_staleness', "
    "'graph_freshness', 'graph_auto_update', 'graph_health'). Cancels the "
    "sweeper's background task on THIS server node and persists "
    "desired_running=False (cks-runtime ADR-015) so it stays stopped "
    "across a restart of this node. Returns the sweeper's own status "
    "dict (same shape as agent_status) reflecting the now-stopped state. "
    "Returns {'agent_id': ..., 'found': false} -- not an error -- if "
    "'agent_id' doesn't match any currently-enabled sweeper; this covers "
    "both an unrecognized id and a real sweeper name that's disabled via "
    "config (a disabled sweeper is never constructed, so it has no "
    "status to report either way -- same convention as agent_status). "
    "IMPORTANT: in a multi-node gossip deployment, this only stops the "
    "sweeper on the node that handles this call -- other nodes' "
    "sweepers of the same agent_id will observe the stop within one "
    "sweep interval (cks-runtime ADR-015 §3), not immediately. Same "
    "process-locality caveat as list_agents/agent_status: in-process "
    "sweepers only, not the standalone agent processes (see "
    "request_process_stop for those).",
    "inputSchema": {
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "Which sweeper to stop, e.g. 'contradiction'. "
                "See list_agents for the current set of ids.",
            },
        },
        "required": ["agent_id"],
    },
}