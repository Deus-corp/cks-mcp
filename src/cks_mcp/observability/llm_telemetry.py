"""
CKS MCP — LLM Telemetry.

In-memory aggregator for LLM *provider* call metrics -- tokens spent,
approximate cost, latency, and success/failure -- parallel to
``cks_mcp.observability.tool_telemetry.ToolTelemetry`` (which tracks MCP *tool* calls),
but one level down: a single MCP tool call to e.g.
``construct_knowledge`` triggers exactly one ``llm_providers.call_ollama``
or ``call_anthropic`` call, which is what gets recorded here.

Updated by ``cks_mcp.llm.providers.call_ollama``/``call_anthropic``
(when a caller passes their ``tool_name``) and read by the
``get_metrics`` tool handler, same wiring as ``tool_telemetry``.

Concurrency note -- why threading.Lock instead of asyncio.Lock:
``ToolTelemetry.record`` is ``async`` and guarded by an ``asyncio.Lock``
because every one of its callers is itself inside an ``async def`` MCP
tool handler. ``llm_providers.call_ollama``/``call_anthropic`` are
deliberately *synchronous* (blocking ``urllib`` calls -- see that
module's docstring), so a caller can't ``await`` a write here even
though it's usually itself running inside an async handler. Recording
is therefore synchronous, guarded by a plain ``threading.Lock``, which
is both correct under threads and safe to call from inside a running
asyncio event loop (unlike trying to schedule/await a coroutine from
sync code, which would need a fresh event loop or a fire-and-forget
task with no error visibility). ``snapshot()``/``reset()`` are
synchronous for the same reason and because aggregating an in-memory
list is fast enough not to need to give up the GIL.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Pricing -- standard published Claude API rates, USD per 1M tokens.
# Anthropic only; Ollama is always free (local model, no API billing).
# Unrecognized model names cost 0 rather than guessing at an unknown rate.
# ---------------------------------------------------------------------------

_PRICING_PER_MILLION_TOKENS: dict[str, tuple[float, float]] = {
    # model substring -> (input $/1M tokens, output $/1M tokens)
    "opus": (15.0, 75.0),
    "sonnet": (3.0, 15.0),
}


def estimate_anthropic_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """
    Estimate USD cost of one Anthropic call from its token usage, using
    standard published per-model rates. Matches by substring against
    ``model`` (e.g. "claude-sonnet-4-6" matches "sonnet") so this stays
    correct across dated model-version strings without needing an exact
    model list. Returns 0.0 for a model name that matches no known tier.
    """
    model_lower = model.lower()
    for substring, (price_in, price_out) in _PRICING_PER_MILLION_TOKENS.items():
        if substring in model_lower:
            return (input_tokens / 1_000_000) * price_in + (output_tokens / 1_000_000) * price_out
    return 0.0


def estimate_tokens_from_chars(text: str) -> int:
    """Rough token estimate for providers (Ollama) that report no usage: chars / 4."""
    return max(0, len(text) // 4)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _LLMCall:
    timestamp: float
    provider: str
    model: str
    tool: str
    tokens: int
    duration_ms: float
    success: bool
    error_type: str | None = None
    cost_estimate: float = 0.0


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


class LLMTelemetry:
    """
    Process-level in-memory store for LLM provider call metrics.

    Thread safety is provided by a plain ``threading.Lock`` (see module
    docstring for why not ``asyncio.Lock``). The ring buffer is capped
    at ``max_calls`` to bound memory usage, same as ``ToolTelemetry``.
    """

    def __init__(self, max_calls: int = 10_000) -> None:
        self._calls: list[_LLMCall] = []
        self._lock = threading.Lock()
        self._max_calls = max_calls

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def record_call(
        self,
        provider: str,
        model: str,
        tool: str,
        tokens: int,
        duration_ms: float,
        success: bool,
        *,
        error_type: str | None = None,
        cost_estimate: float = 0.0,
    ) -> None:
        """Append one LLM call record; evict oldest entries when over budget."""
        entry = _LLMCall(
            timestamp=time.time(),
            provider=provider,
            model=model,
            tool=tool,
            tokens=tokens,
            duration_ms=duration_ms,
            success=success,
            error_type=error_type,
            cost_estimate=cost_estimate,
        )
        with self._lock:
            self._calls.append(entry)
            if len(self._calls) > self._max_calls:
                self._calls = self._calls[-self._max_calls :]

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Return a structured aggregate snapshot suitable for JSON output."""
        with self._lock:
            calls = list(self._calls)

        if not calls:
            return {
                "total_calls": 0,
                "timestamp": datetime.now(UTC).isoformat(),
                "calls_by_provider": {},
                "calls_by_model": {},
                "calls_by_tool": {},
                "total_tokens": 0,
                "total_cost_estimate": 0.0,
                "avg_duration_ms": 0.0,
                "success_rate": 0.0,
                "top_errors": [],
            }

        calls_by_provider: dict[str, int] = defaultdict(int)
        calls_by_model: dict[str, int] = defaultdict(int)
        calls_by_tool: dict[str, int] = defaultdict(int)
        error_counts: dict[str, int] = defaultdict(int)

        total_tokens = 0
        total_cost_estimate = 0.0
        total_duration_ms = 0.0
        success_count = 0

        for call in calls:
            calls_by_provider[call.provider] += 1
            calls_by_model[call.model] += 1
            calls_by_tool[call.tool] += 1
            total_tokens += call.tokens
            total_cost_estimate += call.cost_estimate
            total_duration_ms += call.duration_ms
            if call.success:
                success_count += 1
            elif call.error_type:
                error_counts[call.error_type] += 1

        top_errors_raw = sorted(
            error_counts.items(), key=lambda item: item[1], reverse=True
        )[:5]
        top_errors = [{"type": t, "count": n} for t, n in top_errors_raw]

        return {
            "total_calls": len(calls),
            "timestamp": datetime.now(UTC).isoformat(),
            "calls_by_provider": dict(calls_by_provider),
            "calls_by_model": dict(calls_by_model),
            "calls_by_tool": dict(calls_by_tool),
            "total_tokens": total_tokens,
            "total_cost_estimate": round(total_cost_estimate, 6),
            "avg_duration_ms": round(total_duration_ms / len(calls), 2),
            "success_rate": round(success_count / len(calls), 4),
            "top_errors": top_errors,
        }

    # ------------------------------------------------------------------
    # Reset (useful in tests)
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all recorded calls."""
        with self._lock:
            self._calls.clear()


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

llm_telemetry = LLMTelemetry()

__all__ = [
    "LLMTelemetry",
    "estimate_anthropic_cost",
    "estimate_tokens_from_chars",
    "llm_telemetry",
]
