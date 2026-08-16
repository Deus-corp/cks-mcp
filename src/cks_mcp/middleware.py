"""
CKS MCP — Tool Middleware.

Provides a composable middleware layer that sits between the JSON-RPC
transport (server.py) and tool handler functions.  Each middleware is a
decorator factory with the signature:

    middleware(handler) -> handler

where handler is ``async (runtime, arguments) -> dict``.

Middleware is composed left-to-right so the outermost decorator runs
first:

    handler = require_open_session("session_id")(
                  require_session("session_id")(
                      log_tool_call("my_tool")(my_tool_fn)))

``with_middleware`` is a convenience helper that applies a sequence of
middleware factories in declaration order (first item = outermost):

    handler = with_middleware(
        log_tool_call("my_tool"),
        require_session("session_id"),
        require_open_session("session_id"),
    )(my_tool_fn)

Built-in middleware
-------------------
require_fields(*names)
    Short-circuits with ``missing_parameter`` when any listed field is
    absent from ``arguments``.  Runs before the handler, so it catches
    callers that omit required fields before any session lookup happens.

require_session(*arg_names)
    Looks up each named argument's value as a session_id in the runtime.
    Returns ``session_not_found`` immediately when a session is missing.
    Skips the check when the argument itself is absent (the tool decides
    whether the arg is required via require_fields).

require_open_session(*arg_names)
    Extends ``require_session``: additionally returns ``session_closed``
    when the session exists but is already closed.  Prevents mutations
    on archived sessions from silently succeeding.

refresh_session_from_storage(*arg_names)
    Reloads each named argument's session from persisted storage (when
    already known in-memory) before the handler runs, so a session
    mutated by a *different* process sharing the same storage backend
    (e.g. a standalone ``cks-pipeline-agent``/Critic/Enrichment agent
    process -- see ``cks_mcp.session_refresh`` for the full root-cause
    writeup) is never served stale to this tool call. A no-op for a
    session this process has never seen, so it never masks
    ``require_session``'s own "does this even exist" check.

catch_unhandled_errors
    Last-resort catcher that converts any unhandled exception into an
    ``internal_error`` response rather than surfacing a raw traceback to
    the LLM client.  Should be the outermost layer in the stack.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cks_mcp.errors import internal_error, missing_parameter, session_not_found
from cks_mcp.session_refresh import reload_session_from_storage

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Handler = Callable[..., Any]      # async (runtime, arguments) -> dict
Middleware = Callable[[Handler], Handler]


# ---------------------------------------------------------------------------
# Error helpers not already in errors.py
# ---------------------------------------------------------------------------

def _session_closed(session_id: str) -> dict:
    return {
        "error": "session_closed",
        "message": (
            f"Session '{session_id}' is already closed and cannot be modified. "
            "Open a new session or branch from an existing one."
        ),
    }


# ---------------------------------------------------------------------------
# Middleware factories
# ---------------------------------------------------------------------------

def require_fields(*names: str) -> Middleware:
    """
    Reject calls where any of *names* is absent from ``arguments``.

    Runs before the handler so callers get a clear error instead of a
    confusing KeyError or None-dereference inside the handler.
    """
    def decorator(handler: Handler) -> Handler:
        async def wrapper(runtime, arguments: dict[str, Any]) -> dict[str, Any]:
            for name in names:
                if not arguments.get(name):
                    return missing_parameter(name)
            return await handler(runtime, arguments)
        return wrapper
    return decorator


def require_session(*arg_names: str) -> Middleware:
    """
    Verify that every listed argument, when present, resolves to a known
    session in the runtime.

    Skips the check silently when the argument key is absent — pair with
    ``require_fields`` to make the argument mandatory.
    """
    def decorator(handler: Handler) -> Handler:
        async def wrapper(runtime, arguments: dict[str, Any]) -> dict[str, Any]:
            for arg in arg_names:
                sid = arguments.get(arg)
                if sid is not None and runtime.get_session(sid) is None:
                    return session_not_found(sid)
            return await handler(runtime, arguments)
        return wrapper
    return decorator


def require_open_session(*arg_names: str) -> Middleware:
    """
    Verify that every resolved session is still open (not closed).

    Pairs with ``require_session``; place it *inside* ``require_session``
    so the existence check already ran by the time this guard fires.

    If used standalone it also does the existence check internally,
    so the order of composition is flexible.
    """
    def decorator(handler: Handler) -> Handler:
        async def wrapper(runtime, arguments: dict[str, Any]) -> dict[str, Any]:
            for arg in arg_names:
                sid = arguments.get(arg)
                if sid is None:
                    continue
                session = runtime.get_session(sid)
                if session is None:
                    return session_not_found(sid)
                if session.closed:
                    return _session_closed(sid)
            return await handler(runtime, arguments)
        return wrapper
    return decorator


def refresh_session_from_storage(*arg_names: str) -> Middleware:
    """
    Reload each named session from persisted storage, in place, before
    the handler runs -- see this module's docstring and
    ``cks_mcp.session_refresh`` for why this is needed.

    Only refreshes a session this process already has an in-memory
    copy of (``runtime.get_session(sid)`` is not None); a session id
    unknown here is left for ``require_session``/``require_open_session``
    to report as ``session_not_found`` rather than this middleware
    silently swallowing that case.
    """
    def decorator(handler: Handler) -> Handler:
        async def wrapper(runtime, arguments: dict[str, Any]) -> dict[str, Any]:
            for arg in arg_names:
                sid = arguments.get(arg)
                if not sid:
                    continue
                session = runtime.get_session(sid)
                if session is not None:
                    await reload_session_from_storage(runtime, session)
            return await handler(runtime, arguments)
        return wrapper
    return decorator


def catch_unhandled_errors(handler: Handler) -> Handler:
    """
    Convert any unhandled exception into an ``internal_error`` response.

    Should be the outermost decorator in the stack so it catches errors
    from all inner middleware and the handler itself.  Exceptions are
    re-raised after wrapping only when they are ``asyncio.CancelledError``
    (which must propagate for cooperative cancellation to work).
    """
    import asyncio

    async def wrapper(runtime, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            return await handler(runtime, arguments)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            return internal_error(f"{type(exc).__name__}: {exc}")

    return wrapper


# ---------------------------------------------------------------------------
# Composition helper
# ---------------------------------------------------------------------------

def with_middleware(*middlewares: Middleware) -> Middleware:
    """
    Compose a sequence of middleware factories into a single decorator.

    The first item in *middlewares* becomes the outermost layer
    (runs first on the way in, last on the way out).  This matches
    the natural reading order of a middleware stack::

        handler = with_middleware(
            catch_unhandled_errors,
            log_tool_call("my_tool"),
            require_session("session_id"),
            require_open_session("session_id"),
        )(my_tool_fn)

    Is equivalent to::

        handler = catch_unhandled_errors(
                    log_tool_call("my_tool")(
                      require_session("session_id")(
                        require_open_session("session_id")(my_tool_fn))))
    """
    def combined(handler: Handler) -> Handler:
        for mw in reversed(middlewares):
            handler = mw(handler)
        return handler
    return combined


__all__ = [
    "Handler",
    "Middleware",
    "catch_unhandled_errors",
    "refresh_session_from_storage",
    "require_fields",
    "require_open_session",
    "require_session",
    "with_middleware",
]
