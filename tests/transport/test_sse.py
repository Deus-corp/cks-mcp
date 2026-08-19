"""
Unit tests for cks_mcp.transport.sse.SSEBroadcaster.

Covers:
- A published event reaches a subscriber with no filters.
- session_id filtering only delivers matching events.
- event_types filtering only delivers matching event type names.
- Multiple subscribers each get their own filtered view of the stream.
- A subscriber that stops iterating is unregistered (no leak).
- Bounded queue drops the oldest event under sustained backpressure.
"""

from __future__ import annotations

import asyncio

import pytest
from cks_runtime.adapters.cks_core import CksCoreAdapter
from cks_runtime.events.runtime_event import SessionCreated, VersionCreated
from cks_runtime.runtime import Runtime
from cks_runtime.storage.memory_storage import InMemoryStorage

from cks_mcp.transport.sse import SSEBroadcaster

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def runtime():
    rt = await Runtime.create(core=CksCoreAdapter(), storage=InMemoryStorage())
    try:
        yield rt
    finally:
        await rt.aclose()


async def _next(agen, timeout=1.0):
    return await asyncio.wait_for(agen.__anext__(), timeout=timeout)


async def test_subscriber_receives_published_event(runtime):
    broadcaster = SSEBroadcaster(runtime)
    broadcaster.start()
    try:
        agen = broadcaster.subscribe()
        await runtime.events.publish(SessionCreated(session_id="s1"))
        message = await _next(agen)
        assert message["event"] == "SessionCreated"
        assert message["session_id"] == "s1"
        assert "timestamp" in message
    finally:
        broadcaster.stop()


async def test_session_id_filter_excludes_other_sessions(runtime):
    broadcaster = SSEBroadcaster(runtime)
    broadcaster.start()
    try:
        agen = broadcaster.subscribe(session_id="s1")
        await runtime.events.publish(SessionCreated(session_id="other-session"))
        await runtime.events.publish(SessionCreated(session_id="s1"))
        message = await _next(agen)
        assert message["session_id"] == "s1"
    finally:
        broadcaster.stop()


async def test_event_types_filter_excludes_other_types(runtime):
    broadcaster = SSEBroadcaster(runtime)
    broadcaster.start()
    try:
        agen = broadcaster.subscribe(event_types={"VersionCreated"})
        await runtime.events.publish(SessionCreated(session_id="s1"))
        await runtime.events.publish(
            VersionCreated(session_id="s1", version_id="v1", transaction_id="t1")
        )
        message = await _next(agen)
        assert message["event"] == "VersionCreated"
    finally:
        broadcaster.stop()


async def test_multiple_subscribers_each_get_matching_events(runtime):
    broadcaster = SSEBroadcaster(runtime)
    broadcaster.start()
    try:
        agen_a = broadcaster.subscribe(session_id="a")
        agen_b = broadcaster.subscribe(session_id="b")
        assert broadcaster.subscriber_count() == 2

        await runtime.events.publish(SessionCreated(session_id="a"))
        await runtime.events.publish(SessionCreated(session_id="b"))

        msg_a = await _next(agen_a)
        msg_b = await _next(agen_b)
        assert msg_a["session_id"] == "a"
        assert msg_b["session_id"] == "b"
    finally:
        broadcaster.stop()


async def test_closing_subscriber_unregisters_it(runtime):
    broadcaster = SSEBroadcaster(runtime)
    broadcaster.start()
    try:
        agen = broadcaster.subscribe()
        await runtime.events.publish(SessionCreated(session_id="s1"))
        await _next(agen)
        assert broadcaster.subscriber_count() == 1

        await agen.aclose()
        assert broadcaster.subscriber_count() == 0
    finally:
        broadcaster.stop()


async def test_slow_subscriber_drops_oldest_event_under_backpressure(runtime):
    broadcaster = SSEBroadcaster(runtime, queue_size=2)
    broadcaster.start()
    try:
        agen = broadcaster.subscribe()
        # Publish more events than the queue can hold without anyone
        # draining it -- the oldest should be evicted, not the newest.
        for i in range(5):
            await runtime.events.publish(SessionCreated(session_id=f"s{i}"))

        first = await _next(agen)
        second = await _next(agen)
        # Queue size 2: only the last two published events should survive.
        assert first["session_id"] == "s3"
        assert second["session_id"] == "s4"
    finally:
        broadcaster.stop()


async def test_stop_unsubscribes_from_event_bus(runtime):
    broadcaster = SSEBroadcaster(runtime)
    broadcaster.start()
    broadcaster.stop()

    agen = broadcaster.subscribe()
    await runtime.events.publish(SessionCreated(session_id="s1"))

    with pytest.raises(asyncio.TimeoutError):
        await _next(agen, timeout=0.2)
