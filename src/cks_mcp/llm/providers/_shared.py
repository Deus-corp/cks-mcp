"""
Internal helpers shared by every ``cks_mcp.llm.providers`` submodule
(``ollama``, ``anthropic``, ``openai_compatible``, ``google``).

Not part of the package's public API -- ``cks_mcp.llm.providers``
re-exports each provider's public call_*/*_available/*_host functions,
not these.
"""

from __future__ import annotations

import logging
import time

from cks_mcp.observability.llm_telemetry import llm_telemetry

_logger = logging.getLogger(__name__)


def _record_llm_call(
    *,
    provider: str,
    model: str,
    tool: str,
    tokens: int,
    start: float,
    success: bool,
    error_type: str | None = None,
    cost_estimate: float = 0.0,
) -> None:
    """Shared record_call plumbing for call_ollama/call_anthropic/...: turns a
    monotonic `start` timestamp into a duration_ms and forwards to the
    llm_telemetry singleton. Never raises -- telemetry must never break
    the actual LLM call it's observing."""
    try:
        llm_telemetry.record_call(
            provider,
            model,
            tool,
            tokens,
            (time.monotonic() - start) * 1000,
            success,
            error_type=error_type,
            cost_estimate=cost_estimate,
        )
    except Exception as exc:  # noqa: BLE001 -- telemetry is best-effort, never fatal
        _logger.debug("llm_telemetry.record_call failed: %s", exc)
