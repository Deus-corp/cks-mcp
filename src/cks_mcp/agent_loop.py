"""
Shared "claim -> resolve -> complete/fail/dead-letter" outbox worker
infrastructure, used by every unattended agent built on the persistent
outbox -- the Critic Agent (``cks_mcp.critic_agent``), the Enrichment
Agent (``cks_mcp.enrichment_agent``), and any future agent in the same
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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from cks_runtime.runtime import Runtime


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