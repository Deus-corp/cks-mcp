"""Input schema definitions for the get_metrics tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

GET_METRICS_SCHEMA = {
    "name": "get_metrics",
    "description": "Return runtime metrics, the tool telemetry dashboard, and LLM "
    "provider call telemetry. "
    "'runtime_metrics' contains invocation counts and average execution "
    "times per runtime operation type. "
    "'tool_telemetry' contains per-MCP-tool call counts, success rates, "
    "latency percentiles (p50/p95/p99), and top error types since the "
    "server started. "
    "'critic_agent_metrics' contains Critic Agent counters (processed/"
    "completed/retried/dead_lettered per task_type, lease_lost, and LLM "
    "circuit breaker state) -- process-local to whichever process ran the "
    "Critic Agent loop, so this is all zeros when called against the main "
    "server process while the Critic Agent runs as its own OS process. "
    "'llm_telemetry' contains aggregated LLM provider call stats since "
    "the server started -- total_calls, calls_by_provider/model/tool, "
    "total_tokens, total_cost_estimate (USD; Anthropic calls only, using "
    "standard published per-model rates -- always 0 for Ollama), "
    "avg_duration_ms, success_rate, and top_errors. Covers LLM calls made "
    "by construct_knowledge, arbitrate_inference_conflict's auto_resolve, "
    "resolve_gossip_conflict's auto_resolve, update_registered_graph (via "
    "construct_knowledge), and the Enrichment Agent; like "
    "critic_agent_metrics, it is process-local.",
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