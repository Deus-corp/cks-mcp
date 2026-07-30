"""
Observability utilities for cks-mcp: structured logging and EventBus
subscriptions.

Logs are written to stderr so they never interfere with the MCP
protocol (which uses stdout).
"""

from __future__ import annotations

import dataclasses
import json
import sys
import time
from collections.abc import Callable
from typing import Any

from cks_runtime.events.runtime_event import (
    RuntimeEvent,
    SessionClosed,
    SessionCreated,
    TransactionAborted,
    TransactionCommitted,
    TransactionRolledBack,
    ValidationFailed,
    VersionCreated,
)
from cks_runtime.runtime import Runtime

from cks_mcp.telemetry import tool_telemetry


def _log(entry: dict[str, Any]) -> None:
    """Write a JSON log line to stderr."""
    print(json.dumps(entry, ensure_ascii=False), file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Tool call decorator
# ---------------------------------------------------------------------------


def log_tool_call(tool_name: str) -> Callable:
    """
    Decorator that logs every invocation of an MCP tool handler and
    records the call in the in-memory telemetry dashboard.

    Log entries written to stderr contain: tool, session_id (if present),
    duration_ms, success, and (on failure) error.  The same data is fed
    into ``tool_telemetry`` so that ``get_metrics`` can expose per-tool
    p50/p95/p99 latency and error-type breakdowns.
    """

    def decorator(handler: Callable) -> Callable:
        async def wrapper(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
            start = time.monotonic()
            session_id = arguments.get("session_id", None)
            try:
                result = await handler(runtime, arguments)
                duration_ms = (time.monotonic() - start) * 1000
                is_error = isinstance(result, dict) and "error" in result
                success = not is_error
                error_str = result.get("error") if is_error else None
                _log(
                    {
                        "tool": tool_name,
                        "session_id": session_id,
                        "duration_ms": round(duration_ms, 2),
                        "success": success,
                        "error": error_str,
                    }
                )
                await tool_telemetry.record(
                    tool_name,
                    duration_ms,
                    success,
                    error_type=error_str if error_str else None,
                    session_id=session_id,
                )
                return result
            except Exception as exc:
                duration_ms = (time.monotonic() - start) * 1000
                _log(
                    {
                        "tool": tool_name,
                        "session_id": session_id,
                        "duration_ms": round(duration_ms, 2),
                        "success": False,
                        "error": str(exc),
                    }
                )
                await tool_telemetry.record(
                    tool_name,
                    duration_ms,
                    False,
                    error_type=type(exc).__name__,
                    session_id=session_id,
                )
                raise

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# EventBus subscriptions
# ---------------------------------------------------------------------------


def setup_event_subscriptions(runtime: Runtime) -> None:
    """
    Subscribe to lifecycle events from the Runtime and log them.

    Call this once after creating the Runtime in main().
    """

    def _on_event(event: RuntimeEvent) -> None:
        detail = dataclasses.asdict(event)
        # Remove meta fields that are already in the log envelope
        for key in ("event_id", "created_at", "metadata"):
            detail.pop(key, None)
        _log(
            {
                "event": event.event_type,
                "timestamp": event.created_at.isoformat(),
                "detail": detail,
            }
        )

    runtime.events.subscribe(SessionCreated, _on_event)
    runtime.events.subscribe(SessionClosed, _on_event)
    runtime.events.subscribe(TransactionCommitted, _on_event)
    runtime.events.subscribe(TransactionRolledBack, _on_event)
    runtime.events.subscribe(TransactionAborted, _on_event)
    runtime.events.subscribe(VersionCreated, _on_event)
    runtime.events.subscribe(ValidationFailed, _on_event)