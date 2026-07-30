"""
Unit tests for cks_mcp.middleware.

Tests cover:
- Individual middleware factories (require_fields, require_session,
  require_open_session, catch_unhandled_errors)
- with_middleware composition helper
- Integration: middleware stack applied to a real tool handler shape
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cks_mcp.middleware import (
    catch_unhandled_errors,
    require_fields,
    require_open_session,
    require_session,
    with_middleware,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _ok_handler(runtime, arguments):
    return {"ok": True}


def _make_runtime(sessions: dict | None = None):
    """Return a minimal mock runtime with a get_session method."""
    runtime = MagicMock()
    sessions = sessions or {}

    def _get_session(sid):
        return sessions.get(sid)

    runtime.get_session.side_effect = _get_session
    return runtime


def _open_session(sid: str):
    s = MagicMock()
    s.session_id = sid
    s.closed = False
    return s


def _closed_session(sid: str):
    s = MagicMock()
    s.session_id = sid
    s.closed = True
    return s


# ---------------------------------------------------------------------------
# require_fields
# ---------------------------------------------------------------------------

async def test_require_fields_passes_when_present():
    handler = require_fields("session_id")(_ok_handler)
    result = await handler(None, {"session_id": "abc"})
    assert result == {"ok": True}


async def test_require_fields_blocks_when_missing():
    handler = require_fields("session_id")(_ok_handler)
    result = await handler(None, {})
    assert result["error"] == "missing_parameter"
    assert "session_id" in result["message"]


async def test_require_fields_blocks_on_empty_string():
    handler = require_fields("session_id")(_ok_handler)
    result = await handler(None, {"session_id": ""})
    assert result["error"] == "missing_parameter"


async def test_require_fields_checks_all_names():
    handler = require_fields("a", "b", "c")(_ok_handler)
    # a and b present, c missing
    result = await handler(None, {"a": "1", "b": "2"})
    assert result["error"] == "missing_parameter"
    assert "c" in result["message"]


# ---------------------------------------------------------------------------
# require_session
# ---------------------------------------------------------------------------

async def test_require_session_passes_when_session_exists():
    runtime = _make_runtime({"s1": _open_session("s1")})
    handler = require_session("session_id")(_ok_handler)
    result = await handler(runtime, {"session_id": "s1"})
    assert result == {"ok": True}


async def test_require_session_blocks_when_session_missing():
    runtime = _make_runtime({})
    handler = require_session("session_id")(_ok_handler)
    result = await handler(runtime, {"session_id": "missing"})
    assert result["error"] == "session_not_found"
    assert "missing" in result["message"]


async def test_require_session_skips_when_arg_absent():
    """When the arg key itself is absent, the check is skipped (optional args)."""
    runtime = _make_runtime({})
    handler = require_session("session_id")(_ok_handler)
    result = await handler(runtime, {})
    assert result == {"ok": True}


async def test_require_session_checks_multiple_args():
    runtime = _make_runtime({"s1": _open_session("s1")})
    handler = require_session("source_session_id", "target_session_id")(_ok_handler)
    result = await handler(runtime, {
        "source_session_id": "s1",
        "target_session_id": "missing",
    })
    assert result["error"] == "session_not_found"
    assert "missing" in result["message"]


# ---------------------------------------------------------------------------
# require_open_session
# ---------------------------------------------------------------------------

async def test_require_open_session_passes_for_open_session():
    runtime = _make_runtime({"s1": _open_session("s1")})
    handler = require_open_session("session_id")(_ok_handler)
    result = await handler(runtime, {"session_id": "s1"})
    assert result == {"ok": True}


async def test_require_open_session_blocks_for_closed_session():
    runtime = _make_runtime({"s1": _closed_session("s1")})
    handler = require_open_session("session_id")(_ok_handler)
    result = await handler(runtime, {"session_id": "s1"})
    assert result["error"] == "session_closed"
    assert "s1" in result["message"]


async def test_require_open_session_blocks_when_session_missing():
    runtime = _make_runtime({})
    handler = require_open_session("session_id")(_ok_handler)
    result = await handler(runtime, {"session_id": "ghost"})
    assert result["error"] == "session_not_found"


async def test_require_open_session_skips_when_arg_absent():
    runtime = _make_runtime({})
    handler = require_open_session("session_id")(_ok_handler)
    result = await handler(runtime, {})
    assert result == {"ok": True}


# ---------------------------------------------------------------------------
# catch_unhandled_errors
# ---------------------------------------------------------------------------

async def test_catch_unhandled_errors_passes_success():
    handler = catch_unhandled_errors(_ok_handler)
    result = await handler(None, {})
    assert result == {"ok": True}


async def test_catch_unhandled_errors_wraps_exception():
    async def _boom(runtime, arguments):
        raise ValueError("something went wrong")

    handler = catch_unhandled_errors(_boom)
    result = await handler(None, {})
    assert result["error"] == "internal_error"
    assert "ValueError" in result["message"]
    assert "something went wrong" in result["message"]


async def test_catch_unhandled_errors_reraises_cancelled():
    import asyncio

    async def _cancel(runtime, arguments):
        raise asyncio.CancelledError()

    handler = catch_unhandled_errors(_cancel)
    with pytest.raises(asyncio.CancelledError):
        await handler(None, {})


# ---------------------------------------------------------------------------
# with_middleware composition
# ---------------------------------------------------------------------------

async def test_with_middleware_applies_in_order():
    """Outermost middleware should run first."""
    call_order = []

    def _mw(label):
        def decorator(handler):
            async def wrapper(runtime, arguments):
                call_order.append(f"{label}:in")
                result = await handler(runtime, arguments)
                call_order.append(f"{label}:out")
                return result
            return wrapper
        return decorator

    handler = with_middleware(_mw("A"), _mw("B"), _mw("C"))(_ok_handler)
    await handler(None, {})
    assert call_order == ["A:in", "B:in", "C:in", "C:out", "B:out", "A:out"]


async def test_with_middleware_single_item():
    handler = with_middleware(require_fields("x"))(_ok_handler)
    result = await handler(None, {"x": "1"})
    assert result == {"ok": True}


# ---------------------------------------------------------------------------
# Full stack integration
# ---------------------------------------------------------------------------

async def test_full_stack_blocks_missing_field():
    runtime = _make_runtime({"s1": _open_session("s1")})

    handler = with_middleware(
        catch_unhandled_errors,
        require_fields("session_id"),
        require_open_session("session_id"),
    )(_ok_handler)

    # session_id entirely absent — require_fields fires first
    result = await handler(runtime, {})
    assert result["error"] == "missing_parameter"


async def test_full_stack_blocks_closed_session():
    runtime = _make_runtime({"s1": _closed_session("s1")})

    handler = with_middleware(
        catch_unhandled_errors,
        require_fields("session_id"),
        require_open_session("session_id"),
    )(_ok_handler)

    result = await handler(runtime, {"session_id": "s1"})
    assert result["error"] == "session_closed"


async def test_full_stack_passes_valid_call():
    runtime = _make_runtime({"s1": _open_session("s1")})

    handler = with_middleware(
        catch_unhandled_errors,
        require_fields("session_id"),
        require_open_session("session_id"),
    )(_ok_handler)

    result = await handler(runtime, {"session_id": "s1"})
    assert result == {"ok": True}


async def test_full_stack_catches_handler_exception():
    runtime = _make_runtime({"s1": _open_session("s1")})

    async def _buggy(runtime, arguments):
        raise RuntimeError("oops")

    handler = with_middleware(
        catch_unhandled_errors,
        require_open_session("session_id"),
    )(_buggy)

    result = await handler(runtime, {"session_id": "s1"})
    assert result["error"] == "internal_error"
    assert "oops" in result["message"]
