"""
Server-Sent Events (SSE) streaming for cks-mcp's HTTP transport.

Thin clients such as cks-studio poll the MCP tool surface today; this
module gives them a push channel instead. It bridges the runtime's
``EventBus`` (see ``cks_runtime.events.event_bus``) to any number of
HTTP subscribers connected to ``GET /events``.

Design:

- ``SSEBroadcaster`` subscribes exactly once to the *base*
  ``RuntimeEvent`` type. Per ``EventBus.publish()``, subscribing to the
  base class delivers every event regardless of its concrete subclass,
  so a single subscription (rather than one per event class) keeps this
  module from drifting out of sync as new event types are added
  upstream.
- Each connected client is represented by an ``asyncio.Queue`` with a
  bounded size. If a client is slow to drain its queue, the oldest
  queued event is dropped to make room for the newest one -- an SSE
  client cares about current state more than perfect history, and an
  unbounded queue per slow client is a memory-leak vector.
- Per-subscriber filtering (``session_id`` / ``event_types``) happens
  at broadcast time, not subscribe time, so a single EventBus
  subscription still fans out to differently-filtered clients.

This module has no dependency on aiohttp; ``transport/http_events.py`` (or
``server.py``) wires it to the actual HTTP route.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from cks_runtime.events.runtime_event import RuntimeEvent
from cks_runtime.runtime import Runtime

# Bounded so a subscriber that never reads (e.g. a tab left open on a
# laptop that went to sleep) can't grow without limit. Dropping the
# oldest event on overflow favors "catch up to current state" over
# "replay everything that happened while you were away" -- reasonable
# for UI refresh signals, which is the only consumer today.
_DEFAULT_QUEUE_SIZE = 256


def _event_to_message(event: RuntimeEvent) -> dict[str, Any]:
    """Convert a RuntimeEvent into the wire-format SSE payload."""
    detail = dataclasses.asdict(event)
    session_id = detail.pop("session_id", None)
    # Meta fields already surface as top-level "event"/"timestamp"
    # keys; strip them from detail to avoid duplicating them.
    for key in ("event_id", "created_at", "metadata"):
        detail.pop(key, None)
    return {
        "event": event.event_type,
        "session_id": session_id,
        "timestamp": event.created_at.isoformat(),
        "detail": detail,
    }


@dataclasses.dataclass
class _Subscriber:
    queue: asyncio.Queue[dict[str, Any]]
    session_id: str | None
    event_types: set[str] | None


class SSEBroadcaster:
    """
    Bridges a runtime ``EventBus`` to any number of SSE subscribers.

    Usage::

        broadcaster = SSEBroadcaster(runtime)
        broadcaster.start()
        ...
        async for message in broadcaster.subscribe(session_id="s1"):
            ...  # message is a JSON-serializable dict

    ``start()`` is idempotent-ish (guarded by ``_started``) so it is
    safe to call once per broadcaster instance from server startup.
    """

    def __init__(self, runtime: Runtime, *, queue_size: int = _DEFAULT_QUEUE_SIZE) -> None:
        self._runtime = runtime
        self._queue_size = queue_size
        self._subscribers: dict[str, _Subscriber] = {}
        self._started = False

    def start(self) -> None:
        """Subscribe to the runtime EventBus. Call once at server startup."""
        if self._started:
            return
        self._runtime.events.subscribe(RuntimeEvent, self._on_event)
        self._started = True

    def stop(self) -> None:
        """Unsubscribe from the EventBus (used by tests / clean shutdown)."""
        if not self._started:
            return
        self._runtime.events.unsubscribe(RuntimeEvent, self._on_event)
        self._started = False

    def _on_event(self, event: RuntimeEvent) -> None:
        """EventBus callback: fan the event out to matching subscribers."""
        message = _event_to_message(event)
        for sub in list(self._subscribers.values()):
            if sub.session_id is not None and message["session_id"] != sub.session_id:
                continue
            if sub.event_types is not None and message["event"] not in sub.event_types:
                continue
            self._enqueue(sub, message)

    @staticmethod
    def _enqueue(sub: _Subscriber, message: dict[str, Any]) -> None:
        try:
            sub.queue.put_nowait(message)
        except asyncio.QueueFull:
            # Drop the oldest queued event to make room -- see module
            # docstring. put_nowait() after get_nowait() cannot raise
            # QueueFull again since nothing else touches this queue
            # from other tasks between the two calls (single-threaded
            # event loop).
            try:
                sub.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            sub.queue.put_nowait(message)

    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def subscribe(
        self,
        *,
        session_id: str | None = None,
        event_types: set[str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Register a new subscriber and return an async iterator of
        messages as they arrive.

        Registration happens synchronously, before this method
        returns -- deliberately *not* inside the async-generator body,
        which would only run on the first ``__anext__()``/iteration
        and would race any event published between calling
        ``subscribe()`` and first awaiting the iterator (a call site
        doing ``it = broadcaster.subscribe(); await publish(...)``
        would otherwise silently miss that event).

        Cleans up its registration when the returned generator is
        closed (i.e. when the consumer breaks out of the
        ``async for`` loop or the HTTP client disconnects and the
        caller cancels iteration).
        """
        sub_id = uuid4().hex
        sub = _Subscriber(
            queue=asyncio.Queue(maxsize=self._queue_size),
            session_id=session_id,
            event_types=event_types,
        )
        self._subscribers[sub_id] = sub
        return self._drain(sub_id, sub)

    async def _drain(self, sub_id: str, sub: _Subscriber) -> AsyncIterator[dict[str, Any]]:
        try:
            while True:
                message = await sub.queue.get()
                yield message
        finally:
            self._subscribers.pop(sub_id, None)
