"""
CKS MCP — Tool Telemetry.

In-memory aggregator for per-tool call metrics.  A single process-level
singleton (``tool_telemetry``) is updated by ``observability.log_tool_call``
and read by the ``get_metrics`` tool handler.

Kept separate from ``observability.py`` so that the log-to-stderr
concern and the in-memory aggregation concern stay independent.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _ToolCall:
    timestamp: float
    duration_ms: float
    tool_name: str
    success: bool
    error_type: str | None = None
    session_id: str | None = None


# ---------------------------------------------------------------------------
# Percentile helper
# ---------------------------------------------------------------------------


def _percentile(sorted_data: list[float], p: int) -> float:
    """Return the p-th percentile of a pre-sorted list."""
    if not sorted_data:
        return 0.0
    idx = int((p / 100) * len(sorted_data))
    return sorted_data[min(idx, len(sorted_data) - 1)]


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


class ToolTelemetry:
    """
    Process-level in-memory store for MCP tool call metrics.

    Thread/coroutine safety is provided by an asyncio.Lock so that
    concurrent async tool calls don't race on ``_calls``.

    The ring buffer is capped at ``max_calls`` to bound memory usage.
    """

    def __init__(self, max_calls: int = 10_000) -> None:
        self._calls: list[_ToolCall] = []
        self._lock: asyncio.Lock | None = None  # created lazily inside event loop
        self._max_calls = max_calls

    # ------------------------------------------------------------------
    # Lock — created lazily so the object can be constructed at import
    # time before any event loop exists.
    # ------------------------------------------------------------------

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    async def record(
        self,
        tool_name: str,
        duration_ms: float,
        success: bool,
        *,
        error_type: str | None = None,
        session_id: str | None = None,
    ) -> None:
        """Append a call record; evict oldest entries when over budget."""
        entry = _ToolCall(
            timestamp=time.time(),
            duration_ms=duration_ms,
            tool_name=tool_name,
            success=success,
            error_type=error_type,
            session_id=session_id,
        )
        async with self._get_lock():
            self._calls.append(entry)
            if len(self._calls) > self._max_calls:
                self._calls = self._calls[-self._max_calls :]

    # ------------------------------------------------------------------
    # Read path
    # ------------------------------------------------------------------

    async def dashboard(self) -> dict[str, Any]:
        """Return a structured dashboard snapshot suitable for JSON output."""
        async with self._get_lock():
            calls = list(self._calls)

        if not calls:
            return {
                "total_calls": 0,
                "timestamp": datetime.now(UTC).isoformat(),
                "tools": {},
            }

        # Group by tool name
        by_tool: dict[str, list[_ToolCall]] = defaultdict(list)
        for call in calls:
            by_tool[call.tool_name].append(call)

        tools_stats: dict[str, Any] = {}
        for tool_name, tool_calls in sorted(by_tool.items()):
            durations = sorted(c.duration_ms for c in tool_calls)
            successes = [c for c in tool_calls if c.success]
            errors = [c for c in tool_calls if not c.success]

            # Count distinct error types
            error_counts: dict[str, int] = defaultdict(int)
            for c in errors:
                if c.error_type:
                    error_counts[c.error_type] += 1

            # Explicitly cast values to int for mypy
            error_counts = {k: int(v) for k, v in error_counts.items()}

            error_list: list[dict[str, str | int]] = [
                {"type": t, "count": n} for t, n in error_counts.items()
            ]
            top_errors = sorted(
                error_list,
                key=lambda x: x["count"],
                reverse=True,
            )[:5]

            tools_stats[tool_name] = {
                "calls": len(tool_calls),
                "success_rate": round(len(successes) / len(tool_calls), 4),
                "latency_avg_ms": round(sum(durations) / len(durations), 2),
                "latency_p50_ms": round(_percentile(durations, 50), 2),
                "latency_p95_ms": round(_percentile(durations, 95), 2),
                "latency_p99_ms": round(_percentile(durations, 99), 2),
                "latency_min_ms": round(min(durations), 2),
                "latency_max_ms": round(max(durations), 2),
                "error_count": len(errors),
                "top_errors": top_errors,
            }

        return {
            "total_calls": len(calls),
            "timestamp": datetime.now(UTC).isoformat(),
            "tools": tools_stats,
        }

    # ------------------------------------------------------------------
    # Reset (useful in tests)
    # ------------------------------------------------------------------

    async def reset(self) -> None:
        """Clear all recorded calls."""
        async with self._get_lock():
            self._calls.clear()


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

tool_telemetry = ToolTelemetry()

__all__ = ["ToolTelemetry", "tool_telemetry"]