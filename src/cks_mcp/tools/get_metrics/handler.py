"""
get_metrics: return the current runtime metrics and tool telemetry dashboard.
"""

from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.agents.critic_agent.critic_agent import get_critic_metrics
from cks_mcp.observability.llm_telemetry import llm_telemetry
from cks_mcp.observability.tool_telemetry import tool_telemetry


async def get_metrics(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Return runtime operation metrics, per-tool call telemetry, and LLM
    provider call telemetry (tokens/cost).

    ``critic_agent_metrics`` is process-local: the Critic Agent is a
    separate OS process by design (see ``cks_mcp.agents.critic_agent.critic_agent``'s
    module docstring), so calling this tool against the main server
    process reports all-zero Critic Agent counters even while a
    Critic Agent worker is actively processing tasks elsewhere against
    the same storage. It's only meaningful when read from within the
    same process that ran the loop (tests, or a single-process
    deployment that calls ``run_critic_agent``/``run_once`` directly).
    Cross-process Critic Agent observability needs the metrics
    persisted to shared storage instead of kept in memory -- see
    ROADMAP.md's Critic Agent hardening backlog.

    ``llm_telemetry`` is likewise process-local, and for the same
    reason only reflects LLM calls made by tool handlers running in
    this process (not a separately-run Critic Agent or Enrichment
    Agent process).
    """
    return {
        "runtime_metrics": runtime.metrics.snapshot(),
        "tool_telemetry": await tool_telemetry.dashboard(),
        "critic_agent_metrics": get_critic_metrics(),
        "llm_telemetry": llm_telemetry.snapshot(),
    }