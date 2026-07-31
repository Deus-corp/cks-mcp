"""Input schema definitions for the get_metrics tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

GET_METRICS_SCHEMA = {
    "name": "get_metrics",
    "description": "Return runtime metrics and the tool telemetry dashboard. "
    "'runtime_metrics' contains invocation counts and average execution "
    "times per runtime operation type. "
    "'tool_telemetry' contains per-MCP-tool call counts, success rates, "
    "latency percentiles (p50/p95/p99), and top error types since the "
    "server started.",
    "inputSchema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}
