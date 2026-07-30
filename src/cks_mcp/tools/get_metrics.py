"""
get_metrics: return the current runtime metrics and tool telemetry dashboard.
"""

from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.telemetry import tool_telemetry


async def get_metrics(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return runtime operation metrics and per-tool call telemetry."""
    return {
        "runtime_metrics": runtime.metrics.snapshot(),
        "tool_telemetry": await tool_telemetry.dashboard(),
    }