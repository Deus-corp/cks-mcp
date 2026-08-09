"""Input schema definition for the start_agent tool.

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

START_AGENT_SCHEMA = {
    "name": "start_agent",
    "description": "Start a single in-process reasoning sweeper by 'agent_id' (see "
    "list_agents for the current set of ids, e.g. 'contradiction', "
    "'inference_staleness', 'provenance_staleness', 'temporal_staleness', "
    "'graph_freshness', 'graph_auto_update', 'graph_health'). Starts the "
    "sweeper's background task on THIS server node and persists "
    "desired_running=True (cks-runtime ADR-015) so a later restart of "
    "this node also starts it. Returns the sweeper's own status dict "
    "(same shape as agent_status) reflecting the now-running state. "
    "Returns {'agent_id': ..., 'found': false} -- not an error -- if "
    "'agent_id' doesn't match any currently-enabled sweeper; this covers "
    "both an unrecognized id and a real sweeper name that's disabled via "
    "config (a config-disabled sweeper is never constructed at all, so "
    "this tool cannot start it -- config enablement is a separate gate "
    "this override does not affect, per ADR-015 §2). IMPORTANT: in a "
    "multi-node gossip deployment, this only restarts the sweeper on "
    "the node that handles this call -- it does NOT propagate to other "
    "nodes whose sweeper of the same agent_id isn't currently running "
    "(unlike stop_agent, which does propagate within one sweep interval "
    "-- see cks-runtime ADR-015 §3 for why start and stop are "
    "deliberately asymmetric here). Same process-locality caveat as "
    "list_agents/agent_status: in-process sweepers only, not the "
    "standalone agent processes (those cannot be started by any MCP "
    "tool -- see cks-runtime ADR-016 §4).",
    "inputSchema": {
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "Which sweeper to start, e.g. 'contradiction'. "
                "See list_agents for the current set of ids.",
            },
        },
        "required": ["agent_id"],
    },
}