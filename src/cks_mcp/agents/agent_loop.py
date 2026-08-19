"""
Shared "claim -> resolve -> complete/fail/dead-letter" outbox worker
infrastructure, used by every unattended agent built on the persistent
outbox -- the Critic Agent (``cks_mcp.agents.critic_agent.critic_agent``), the Enrichment
Agent (``cks_mcp.agents.enrichment_agent.enrichment_agent``), and any future agent in the same
family (see ROADMAP.md's "Future Agents" backlog). Factored out here
once a second agent needed the identical claim/heartbeat/lease-renewal
logic, rather than copy-pasted per agent.

``claim_conflict_task``/``complete_conflict_task``/``fail_conflict_task``/
``dead_letter_conflict_task`` are themselves already generic over
``task_type`` despite the "conflict" in their names (see that tool's
own docstring) -- every agent built on this module reuses those same
four MCP tools directly rather than each defining its own claim/
complete/fail/dead-letter tool per task_type.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from os import getpid
from typing import Any
from uuid import uuid4

from cks_runtime.runtime import Runtime
from cks_runtime.storage.storage import AgentLivenessRecord

# ADR-016 §3: a value for last_heartbeat_at far enough in the past that
# the existing TTL check (alive = now - last_heartbeat_at <= 3 *
# liveness_interval_s) fails immediately, regardless of
# liveness_interval_s -- used by LivenessReporter.stop()'s final write
# to make a graceful exit read as `stopped` right away instead of
# waiting out the TTL window.
_EPOCH_ISO = datetime.fromtimestamp(0, tz=UTC).isoformat()


@dataclass(slots=True)
class Resolution:
    """The outcome of attempting to resolve one claimed outbox task."""

    resolved: bool
    detail: str | None = None


async def run_resolver_with_heartbeat(
    runtime: Runtime,
    resolver: Callable[[Runtime, dict[str, Any]], Awaitable[Resolution]],
    task: dict[str, Any],
    task_id: int,
    heartbeat_interval: float,
) -> tuple[Resolution, bool]:
    """
    Run ``resolver(runtime, task)`` while periodically renewing the
    outbox lease on ``task_id`` via ``touch_outbox_task``, so a slow
    resolution (an LLM call, a web fetch, a chain of both) doesn't
    outlive ``dequeue_next_outbox_task``'s stale-lease reclaim window
    and get picked up by a second worker while this one is still
    working it.

    Returns ``(resolution, lease_lost)``. If ``lease_lost`` is True, a
    renewal came back False -- some other worker (or a supervisor that
    restarted this same one) already reclaimed the task, so its
    outcome must not be reported via complete/fail/dead_letter: doing
    so would race with whoever holds the lease now.
    """
    lease_lost = False

    async def _heartbeat() -> None:
        nonlocal lease_lost
        while True:
            await asyncio.sleep(heartbeat_interval)
            renewed = await runtime.storage.touch_outbox_task(task_id)
            if not renewed:
                lease_lost = True
                return

    heartbeat_task = asyncio.create_task(_heartbeat())
    try:
        resolution = await resolver(runtime, task)
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task

    return resolution, lease_lost


class LivenessReporter:
    """
    Reports this standalone-agent process's liveness to
    ``storage.cks_agent_liveness`` (cks-runtime ADR-014) -- a distinct
    concept from ``run_resolver_with_heartbeat``'s task-lease heartbeat
    above: this one says "the process is alive", independent of
    whether it currently holds any outbox task lease.

    One instance per process, created once at process startup with a
    fresh ``instance_id``. ``start()`` writes the initial row and spawns
    a background tick that re-upserts every ``liveness_interval``
    seconds; ``stop()`` cancels it. ``set_current_task``/
    ``clear_current_task`` update ``current_task_id``/
    ``current_task_type`` opportunistically (best effort -- see
    ADR-014 §2) so the next tick reports what this process is doing,
    without forcing an extra write on every claim/release.

    A storage backend that doesn't support agent liveness
    (``supports_agent_liveness`` False, e.g. in-memory storage in
    tests) makes every write a silent no-op, same convention as the
    outbox's ``supports_outbox`` gate -- callers don't need to check
    it themselves.

    ADR-016 extends this class with remote-stop support: passing
    ``stop_event`` (the same ``asyncio.Event`` each ``run_*_agent``
    function already creates for ``SIGTERM``/``SIGINT`` handling) makes
    a ``request_agent_stop`` MCP call and a signal converge on the
    exact same shutdown path -- see ADR-016 §2 for the rationale. When
    omitted, this class behaves exactly as it did before ADR-016 (no
    remote-stop check, ``stop()`` no longer backdates the heartbeat).
    """

    def __init__(
        self,
        runtime: Runtime,
        process_kind: str,
        liveness_interval: float,
        *,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        self._runtime = runtime
        self._process_kind = process_kind
        self._interval = liveness_interval
        self._instance_id = str(uuid4())
        self._hostname = socket.gethostname()
        self._pid = getpid()
        self._started_at = datetime.now(UTC).isoformat()
        self._current_task_id: int | None = None
        self._current_task_type: str | None = None
        self._tick_task: asyncio.Task[None] | None = None
        self._stop_event = stop_event

    def set_current_task(self, task_id: int, task_type: str) -> None:
        self._current_task_id = task_id
        self._current_task_type = task_type

    def clear_current_task(self) -> None:
        self._current_task_id = None
        self._current_task_type = None

    async def _write(self, *, last_heartbeat_at_override: str | None = None) -> None:
        record = AgentLivenessRecord(
            instance_id=self._instance_id,
            process_kind=self._process_kind,
            hostname=self._hostname,
            pid=self._pid,
            liveness_interval_s=self._interval,
            started_at=self._started_at,
            last_heartbeat_at=last_heartbeat_at_override or datetime.now(UTC).isoformat(),
            current_task_id=self._current_task_id,
            current_task_type=self._current_task_type,
        )
        result = self._runtime.storage.upsert_agent_liveness(record)
        if asyncio.iscoroutine(result):
            await result

    async def _tick_forever(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            with contextlib.suppress(Exception):
                # A transient storage error here must never crash the
                # agent's actual work loop -- liveness reporting is
                # observability, not the agent's core function.
                await self._write()
                if self._stop_event is not None:
                    # ADR-016 §2: read our own row back on the same
                    # cadence, so a `request_agent_stop` MCP call
                    # (recorded by a different process) is observed and
                    # converged onto the exact same shutdown path as
                    # SIGTERM/SIGINT.
                    record = self._runtime.storage.get_agent_liveness(self._instance_id)
                    if asyncio.iscoroutine(record):
                        record = await record
                    if record is not None and record.desired_state == "stop_requested":
                        self._stop_event.set()
                        return

    async def start(self) -> None:
        """Write the initial row and start the background tick."""
        with contextlib.suppress(Exception):
            await self._write()
        self._tick_task = asyncio.create_task(self._tick_forever())

    async def stop(self) -> None:
        if self._tick_task is not None:
            self._tick_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._tick_task
            self._tick_task = None
        with contextlib.suppress(Exception):
            # ADR-016 §3: backdate last_heartbeat_at far enough into the
            # past that the existing TTL check fails immediately, so a
            # cleanly-exited process reads as `stopped` right away
            # instead of up to `3 * liveness_interval_s` later. A crash
            # (no chance to run this) still degrades the old way, via
            # the TTL alone -- this only speeds up the voluntary-exit
            # case, it doesn't change crash detection.
            self._current_task_id = None
            self._current_task_type = None
            await self._write(last_heartbeat_at_override=_EPOCH_ISO)