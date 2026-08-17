"""
Embedded agents (ADR-012): run the four standalone agent processes
(``cks_mcp.pipeline_agent``, ``critic_agent``, ``enrichment_agent``,
``fork_resolution_agent``) as background ``asyncio`` tasks inside the
main ``cks-mcp`` server, instead of requiring an operator to launch
each as its own separate OS process (``cks-pipeline-agent``,
``cks-critic-agent``, ``cks-enrichment-agent``, ``cks-fork-agent``).

This is deliberately an *in-process* mechanism, not process spawning:
cks-runtime ADR-016 §4 rules out tool-initiated OS-process spawning as
out of ``cks-mcp``'s process-supervision scope (see cks-mcp ADR-010),
and that decision stands. Nothing here spawns a subprocess -- each
"agent" is just its existing ``run_*_agent()`` coroutine, already
factored to construct its own ``Runtime`` against the same storage
path as the main server, scheduled as an ``asyncio.Task`` on the same
event loop. It's opt-in and off by default so it changes no existing
deployment's behaviour unless explicitly enabled.

Each embedded agent gets its own ``asyncio.Event`` passed in as
``stop_event`` (see e.g. ``run_critic_agent``'s docstring) so it does
*not* install its own ``SIGTERM``/``SIGINT`` handlers -- the main
server process already owns those, and four coroutines each calling
``loop.add_signal_handler`` for the same signal on the same loop would
silently clobber one another. Shutdown here is cooperative: the
server calls ``stop_embedded_agents()``, which sets every stop_event
and awaits each task, giving each agent's own ``finally`` block
(liveness reporter stop, ``runtime.aclose()``) a chance to run before
the task is done. If an agent hasn't exited within
``CKS_EMBEDDED_AGENTS_SHUTDOWN_TIMEOUT`` seconds of its stop_event
being set, its task is cancelled outright rather than blocking server
shutdown forever.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from cks_mcp.critic_agent import CriticAgentSettings, run_critic_agent
from cks_mcp.enrichment_agent import EnrichmentAgentSettings, run_enrichment_agent
from cks_mcp.fork_resolution_agent import (
    ForkResolutionAgentSettings,
    run_fork_agent,
)
from cks_mcp.pipeline_agent import PipelineAgentSettings, run_pipeline_agent

_DEFAULT_SHUTDOWN_TIMEOUT_SECONDS = 10.0

# Runner signature shared by all four agents: an async function taking
# only keyword args, one of which is always `stop_event`.
_Runner = Callable[..., Coroutine[Any, Any, None]]


@dataclass(frozen=True, slots=True)
class _AgentSpec:
    process_kind: str
    """Same vocabulary as ``process_status``/``request_process_stop``
    (cks-mcp ADR-008/ADR-010): 'pipeline', 'critic', 'enrichment',
    'fork_resolution'."""

    env_flag: str
    """Per-agent opt-in env var, e.g. ``CKS_EMBED_CRITIC_AGENT``."""

    runner: _Runner
    settings_from_env: Callable[[], Any]


_AGENT_SPECS: tuple[_AgentSpec, ...] = (
    _AgentSpec(
        "pipeline",
        "CKS_EMBED_PIPELINE_AGENT",
        run_pipeline_agent,
        PipelineAgentSettings.from_env,
    ),
    _AgentSpec(
        "critic",
        "CKS_EMBED_CRITIC_AGENT",
        run_critic_agent,
        CriticAgentSettings.from_env,
    ),
    _AgentSpec(
        "enrichment",
        "CKS_EMBED_ENRICHMENT_AGENT",
        run_enrichment_agent,
        EnrichmentAgentSettings.from_env,
    ),
    _AgentSpec(
        "fork_resolution",
        "CKS_EMBED_FORK_RESOLUTION_AGENT",
        run_fork_agent,
        ForkResolutionAgentSettings.from_env,
    ),
)


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in ("1", "true", "yes", "on")


def _agent_enabled(spec: _AgentSpec) -> bool:
    """``CKS_EMBEDDED_AGENTS=true`` turns every agent on by default;
    a per-agent flag can turn one on/off individually and always wins
    over the blanket flag, so e.g.
    ``CKS_EMBEDDED_AGENTS=true CKS_EMBED_CRITIC_AGENT=false`` embeds
    pipeline/enrichment/fork_resolution but not critic."""
    per_agent = os.environ.get(spec.env_flag)
    if per_agent is not None:
        return _truthy(per_agent)
    return _truthy(os.environ.get("CKS_EMBEDDED_AGENTS"))


@dataclass(slots=True)
class EmbeddedAgentHandle:
    process_kind: str
    task: asyncio.Task[None]
    stop_event: asyncio.Event


def start_embedded_agents(storage_path: str) -> list[EmbeddedAgentHandle]:
    """Start every agent enabled via env vars (see ``_agent_enabled``)
    as a background task sharing ``storage_path`` with the main
    server's own ``Runtime``. Returns the (possibly empty) list of
    handles; callers should keep this to pass to
    ``stop_embedded_agents()`` on shutdown.

    Safe to call even when nothing is enabled -- returns ``[]`` and
    does not touch storage or construct any ``Runtime``.
    """
    handles: list[EmbeddedAgentHandle] = []
    for spec in _AGENT_SPECS:
        if not _agent_enabled(spec):
            continue

        settings = spec.settings_from_env()
        # Embedded agents always share the main server's storage path,
        # regardless of whatever CKS_*_STORAGE_PATH env var the
        # per-agent settings picked up -- there is exactly one
        # database in embedded mode, the server's own.
        settings.storage_path = storage_path

        stop_event = asyncio.Event()
        task: asyncio.Task[None] = asyncio.create_task(
            spec.runner(settings=settings, stop_event=stop_event),
            name=f"cks-embedded-agent-{spec.process_kind}",
        )
        handles.append(
            EmbeddedAgentHandle(
                process_kind=spec.process_kind, task=task, stop_event=stop_event
            )
        )
        print(
            f"[CKS-MCP] Embedded agent started: {spec.process_kind} "
            f"(storage_path={storage_path!r})",
            file=sys.stderr,
        )

    return handles


async def stop_embedded_agents(
    handles: list[EmbeddedAgentHandle],
    *,
    timeout: float = _DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
) -> None:
    """Signal every embedded agent to stop and wait (up to ``timeout``
    seconds total) for its task to finish, so each agent's own cleanup
    (``LivenessReporter.stop()``, ``runtime.aclose()``) runs instead of
    being cut off mid-write. Any task still running after the timeout
    is cancelled outright rather than blocking server shutdown."""
    if not handles:
        return

    for handle in handles:
        handle.stop_event.set()

    tasks = [handle.task for handle in handles]
    _done, pending = await asyncio.wait(tasks, timeout=timeout)

    for task in pending:
        task.cancel()
    if pending:
        await asyncio.wait(pending)

    for handle in handles:
        exc: BaseException | None = None
        if handle.task.done() and not handle.task.cancelled():
            exc = handle.task.exception()
        if exc is not None:
            print(
                f"[CKS-MCP] Embedded agent {handle.process_kind!r} exited "
                f"with an error: {exc!r}",
                file=sys.stderr,
            )
        else:
            print(
                f"[CKS-MCP] Embedded agent stopped: {handle.process_kind}",
                file=sys.stderr,
            )