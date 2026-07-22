"""
Observability utilities for cks-mcp: structured logging and EventBus
subscriptions.

Logs are written to stderr so they never interfere with the MCP
protocol (which uses stdout).
"""

from __future__ import annotations

import json
import sys
import time
import dataclasses
from typing import Any, Callable

from cks_runtime.runtime import Runtime
from cks_runtime.events.runtime_event import (
    RuntimeEvent,
    SessionCreated,
    SessionClosed,
    TransactionCommitted,
    TransactionRolledBack,
    TransactionAborted,
    VersionCreated,
    ValidationFailed,
)


def _log(entry: dict[str, Any]) -> None:
    """Write a JSON log line to stderr."""
    print(json.dumps(entry, ensure_ascii=False), file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Tool call decorator
# ---------------------------------------------------------------------------

def log_tool_call(tool_name: str) -> Callable:
    """
    Decorator that logs every invocation of an MCP tool handler.

    Log entries contain: tool, session_id (if present), duration_ms,
    success, and (on failure) error.
    """
    def decorator(handler: Callable) -> Callable:
        def wrapper(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
            start = time.monotonic()
            session_id = arguments.get("session_id", None)
            try:
                result = handler(runtime, arguments)
                duration_ms = (time.monotonic() - start) * 1000
                is_error = isinstance(result, dict) and "error" in result
                _log({
                    "tool": tool_name,
                    "session_id": session_id,
                    "duration_ms": round(duration_ms, 2),
                    "success": not is_error,
                    "error": result.get("error") if is_error else None,
                })
                return result
            except Exception as exc:
                duration_ms = (time.monotonic() - start) * 1000
                _log({
                    "tool": tool_name,
                    "session_id": session_id,
                    "duration_ms": round(duration_ms, 2),
                    "success": False,
                    "error": str(exc),
                })
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
        _log({
            "event": event.event_type,
            "timestamp": event.created_at.isoformat(),
            "detail": detail,
        })

    runtime.events.subscribe(SessionCreated, _on_event)
    runtime.events.subscribe(SessionClosed, _on_event)
    runtime.events.subscribe(TransactionCommitted, _on_event)
    runtime.events.subscribe(TransactionRolledBack, _on_event)
    runtime.events.subscribe(TransactionAborted, _on_event)
    runtime.events.subscribe(VersionCreated, _on_event)
    runtime.events.subscribe(ValidationFailed, _on_event)