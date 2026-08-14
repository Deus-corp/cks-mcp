"""
Integration tests for the GET /events SSE endpoint (http_events.py).

Spins up a real aiohttp server (via aiohttp.test_utils), connects to
/events with a streaming GET, triggers a runtime event, and checks the
raw SSE body for the expected JSON line. Also covers session_id and
event_types filtering end-to-end through the HTTP layer.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from cks_runtime.events.runtime_event import SessionCreated
from cks_runtime.runtime import Runtime
from cks_runtime.storage.memory_storage import InMemoryStorage
from cks_runtime_plugins.cks_core import CksCoreAdapter

from cks_mcp.http_events import register_sse_routes

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def runtime():
    rt = await Runtime.create(core=CksCoreAdapter(), storage=InMemoryStorage())
    try:
        yield rt
    finally:
        await rt.aclose()


@pytest.fixture
async def client(runtime):
    app = web.Application()
    app["runtime"] = runtime
    broadcaster = register_sse_routes(app, runtime)
    test_client = TestClient(TestServer(app))
    await test_client.start_server()
    try:
        yield test_client
    finally:
        broadcaster.stop()
        await test_client.close()


async def _read_one_sse_message(response, timeout: float = 2.0) -> dict:
    """Read a single ``data: {...}\\n\\n`` frame from a streaming response."""
    async def _read():
        buf = b""
        while b"\n\n" not in buf:
            chunk = await response.content.read(1024)
            if not chunk:
                break
            buf += chunk
        line = buf.split(b"\n\n", 1)[0]
        assert line.startswith(b"data: ")
        return json.loads(line[len(b"data: "):].decode("utf-8"))

    return await asyncio.wait_for(_read(), timeout=timeout)


async def test_events_endpoint_streams_published_event(client, runtime):
    response = await client.get("/events")
    assert response.status == 200
    assert response.headers["Content-Type"].startswith("text/event-stream")
    assert response.headers["Cache-Control"] == "no-cache"

    await runtime.events.publish(SessionCreated(session_id="s1"))

    message = await _read_one_sse_message(response)
    assert message["event"] == "SessionCreated"
    assert message["session_id"] == "s1"
    assert "timestamp" in message
    response.close()


async def test_events_endpoint_filters_by_path_session_id(client, runtime):
    response = await client.get("/events/s1")
    assert response.status == 200

    await runtime.events.publish(SessionCreated(session_id="other"))
    await runtime.events.publish(SessionCreated(session_id="s1"))

    message = await _read_one_sse_message(response)
    assert message["session_id"] == "s1"
    response.close()


async def test_events_endpoint_filters_by_query_session_id(client, runtime):
    response = await client.get("/events", params={"session_id": "s2"})
    assert response.status == 200

    await runtime.events.publish(SessionCreated(session_id="other"))
    await runtime.events.publish(SessionCreated(session_id="s2"))

    message = await _read_one_sse_message(response)
    assert message["session_id"] == "s2"
    response.close()


async def test_events_endpoint_filters_by_event_types(client, runtime):
    response = await client.get(
        "/events", params={"event_types": "SessionClosed,VersionCreated"}
    )
    assert response.status == 200

    # SessionCreated should be filtered out; publish a SessionClosed
    # (also in the allow-list) so we have something to actually read.
    await runtime.events.publish(SessionCreated(session_id="s1"))
    from cks_runtime.events.runtime_event import SessionClosed

    await runtime.events.publish(SessionClosed(session_id="s1"))

    message = await _read_one_sse_message(response)
    assert message["event"] == "SessionClosed"
    response.close()
