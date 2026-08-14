"""
HTTP wiring for the ``/events`` SSE endpoint.

Kept separate from ``server.py`` so the aiohttp-specific request/response
plumbing doesn't clutter the JSON-RPC handler, and so ``sse.py`` (the
actual broadcaster) stays free of any aiohttp import.
"""

from __future__ import annotations

import asyncio
import json

from aiohttp import web
from aiohttp.web import Request, StreamResponse

from cks_mcp.sse import SSEBroadcaster

# Extension point for future auth: if CKS_MCP_HTTP_TOKEN is set, callers
# would be expected to send it (e.g. as an `Authorization: Bearer <token>`
# header or `?token=` query param) and this handler would reject
# mismatches with 401 before opening the stream. Not implemented yet --
# today CKS_MCP_HTTP_TOKEN, if set, has no effect. Left as a named
# constant (rather than inlining the env var lookup) so the extension
# point is easy to find later.
_AUTH_TOKEN_ENV_VAR = "CKS_MCP_HTTP_TOKEN"


async def handle_sse(request: Request) -> StreamResponse:
    """
    ``GET /events`` and ``GET /events/{session_id}``.

    Query params:
      - ``session_id``: subscribe to a single session's events only.
        Also accepted as a path segment (``/events/{session_id}``); the
        path segment takes precedence if both are given. If neither is
        given, all sessions' events are streamed.
      - ``event_types``: comma-separated list of event type names
        (e.g. ``VersionCreated,TransactionCommitted``) to filter to.
        If omitted, all event types are streamed.

    Auth: none yet -- see ``_AUTH_TOKEN_ENV_VAR`` above for the planned
    extension point.
    """
    broadcaster: SSEBroadcaster = request.app["sse_broadcaster"]

    session_id = request.match_info.get("session_id") or request.query.get("session_id")
    event_types_param = request.query.get("event_types")
    event_types = (
        {t.strip() for t in event_types_param.split(",") if t.strip()}
        if event_types_param
        else None
    )

    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # aiohttp_cors adds the configured CORS headers itself once
            # the route is registered with cors.add() in server.py, so
            # nothing CORS-specific is needed here.
            "X-Accel-Buffering": "no",  # disable nginx buffering, if fronted by one
        },
    )
    await response.prepare(request)

    try:
        async for message in broadcaster.subscribe(
            session_id=session_id, event_types=event_types
        ):
            payload = json.dumps(message, ensure_ascii=False)
            await response.write(f"data: {payload}\n\n".encode())
    except (ConnectionResetError, asyncio.CancelledError):
        # Client disconnected -- nothing to clean up here beyond what
        # the broadcaster's subscribe() generator already does in its
        # `finally` block when this async-for loop unwinds.
        pass
    return response


def register_sse_routes(app: web.Application, runtime) -> SSEBroadcaster:
    """
    Create an ``SSEBroadcaster`` for ``runtime``, start it, stash it on
    the app, and register the ``/events`` routes. Returns the
    broadcaster so callers (tests, or server shutdown) can hold a
    reference -- e.g. to call ``.stop()``.
    """
    broadcaster = SSEBroadcaster(runtime)
    broadcaster.start()
    app["sse_broadcaster"] = broadcaster
    app.router.add_get("/events", handle_sse)
    app.router.add_get("/events/{session_id}", handle_sse)
    return broadcaster
