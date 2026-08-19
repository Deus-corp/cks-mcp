"""Input schema definition for the list_agents tool.

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

LIST_AGENTS_SCHEMA = {
    "name": "list_agents",
    "description": "Return the status of every currently-enabled in-process reasoning "
    "sweeper (ContradictionSweeper, InferenceStalenessSweeper, "
    "ProvenanceStalenessSweeper, TemporalStalenessSweeper, "
    "GraphFreshnessSweeper, GraphAutoUpdateSweeper, GraphHealthSweeper) -- "
    "the background workers that periodically re-check sessions/graphs and "
    "escalate findings as outbox tasks. Each entry has 'agent_id' (a stable "
    "slug, e.g. 'contradiction' or 'inference_staleness' -- pass this to "
    "agent_status for a single sweeper), 'kind' (always 'sweeper' for now), "
    "'running', 'interval_seconds', 'last_run_at' (ISO 8601, null if it "
    "hasn't run yet this process), 'last_run_duration_ms', "
    "'last_result_count' (items the last pass escalated/considered; null "
    "for a sweeper that doesn't report a count), and 'last_error' (the "
    "last exception's type and message, null if the last run succeeded or "
    "it hasn't run yet). A sweeper disabled via its Runtime config "
    "interval (e.g. contradiction_sweep_interval=None) is omitted entirely "
    "rather than listed as not-running -- 'not configured' and 'configured "
    "but not currently running' are different things this distinguishes. "
    "IMPORTANT: this covers only in-process sweepers, i.e. background "
    "workers running inside this MCP server's own process. It does NOT "
    "cover the standalone agent processes (Critic Agent, Enrichment Agent, "
    "Fork Resolution Agent, Pipeline Agent) -- those run as separate OS "
    "processes with their own Runtime instance and storage connection, and "
    "are not currently observable through any MCP tool (same process-"
    "locality caveat as get_metrics's critic_agent_metrics).",
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
