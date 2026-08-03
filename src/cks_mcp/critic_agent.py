"""
Critic Agent: an autonomous, unattended process that resolves gossip
and inference conflicts from the persistent outbox.

This is the "Critic Agent runtime loop" item from ROADMAP.md's "Next
Up" section -- the last missing piece of the Critic-agent design. All
of the supporting plumbing already shipped before this module:

- Detection: ``InferenceStalenessSweeper`` (cks-runtime, ADR-009),
  ``GossipConflictDetected`` (ADR-008).
- Queueing: gossip/inference conflicts are dual-written into the
  persistent outbox (``cks_outbox_tasks``, task_type
  ``"gossip_conflict"``/``"inference_conflict"``) by
  ``cks_mcp.gossip``/``cks_mcp.observability`` whenever the storage
  backend supports it (SQLite or Postgres -- never the default
  in-memory backend).
- Claiming: ``claim_conflict_task`` atomically dequeues one task at a
  time from a *separate* Runtime/process, exactly what this module
  needs -- see that tool's own docstring for why a separate process
  can't just read the in-process ``ConflictInbox`` the interactive
  ``list_gossip_conflicts``/``list_inference_conflicts`` tools use.
- Resolution: ``merge_branch`` (gossip) and
  ``arbitrate_inference_conflict`` with ``auto_resolve``+``commit``
  (inference).
- Outcome: ``complete_conflict_task`` / ``fail_conflict_task`` /
  ``dead_letter_conflict_task``.

This module is the loop that ties them together: it runs as its own
OS process with its *own* ``Runtime`` instance pointed at the same
persistent storage the main ``cks-mcp`` server uses (same SQLite file,
or the same Postgres DSN), polls both queues, and drives each task
through claim -> resolve -> complete/fail/dead-letter. It does not
talk MCP/JSON-RPC to the running server -- there is no protocol
boundary here to cross, since ``claim_conflict_task`` and friends are
already plain async functions over a shared ``Runtime.storage``; the
"separate process" boundary that matters is *two OS processes sharing
one database*, not two processes speaking MCP to each other.

Resolution policy (deliberately simple, matching the "own policy" half
of ROADMAP.md's "decides on resolutions (via auto_resolve or its own
policy)"):

- ``gossip_conflict``: call ``merge_branch(target_session_id=task's
  own session_id, source_session_id=payload's source_session_id)``.
  A clean merge completes the task. A structural merge conflict (two
  branches touched the same object incompatibly) is not something this
  agent guesses at -- it dead-letters the task for human review via
  ``resolutions``, rather than picking a side with no evidence either
  way.
- ``inference_conflict``: only ``CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT``
  diagnostics name a ``conclusion_id`` that ``arbitrate_inference_conflict``
  knows how to arbitrate (``CKS-EXT-STALE-PREMISE`` findings describe a
  different condition -- a premise going stale, not two active steps
  disputing a conclusion -- and have no arbitration primitive yet, so
  they are dead-lettered for a human to look at). Every arbitrable
  conclusion_id in one task is resolved via ONE batch
  ``arbitrate_inference_conflict(auto_resolve=True, commit=True)``
  call, reusing that tool's own LLM provider dispatch
  (``CKS_LLM_PROVIDER`` etc. -- see that tool's docstring).

A task is dead-lettered (not retried forever) once its retry_count
would reach ``max_retries`` (default 5, same cap philosophy as
``OutboxEmbeddingWorker``): a conflict the agent still can't resolve
after that many attempts is treated as needing a human, not another
identical retry.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import traceback
from dataclasses import dataclass, field
from typing import Any

from cks_runtime.config import RuntimeConfig
from cks_runtime.runtime import Runtime
from cks_runtime_plugins.cks_core import CksCoreAdapter

from cks_mcp.paths import data_dir
from cks_mcp.tools.arbitrate_inference_conflict.handler import (
    arbitrate_inference_conflict,
)
from cks_mcp.tools.claim_conflict_task.handler import claim_conflict_task
from cks_mcp.tools.complete_conflict_task.handler import complete_conflict_task
from cks_mcp.tools.dead_letter_conflict_task.handler import dead_letter_conflict_task
from cks_mcp.tools.fail_conflict_task.handler import fail_conflict_task
from cks_mcp.tools.merge.handler import merge_branch

# The only diagnostic code arbitrate_inference_conflict knows how to
# resolve. CKS-EXT-STALE-PREMISE (the other code InferenceConflict-
# Detected can carry, see cks-runtime ADR-002) describes a premise
# that has gone stale, not two active InferenceSteps disputing a
# conclusion -- there is no arbitration primitive for it yet, so those
# diagnostics are left for a human via the dead-letter queue instead
# of guessing at a resolution this agent has no tool to apply.
_ARBITRABLE_DIAGNOSTIC_CODE = "CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT"

# Same backoff cap philosophy as OutboxEmbeddingWorker/fail_conflict_task:
# a conflict is dead-lettered rather than retried forever once it's
# failed this many times.
_DEFAULT_MAX_RETRIES = 5
_DEFAULT_POLL_INTERVAL_SECONDS = 5.0

_TASK_TYPES = ("gossip_conflict", "inference_conflict")


@dataclass(slots=True)
class CriticAgentSettings:
    """Runtime-tunable knobs for the Critic Agent loop, from env vars."""

    poll_interval: float = _DEFAULT_POLL_INTERVAL_SECONDS
    max_retries: int = _DEFAULT_MAX_RETRIES
    storage_path: str = field(default_factory=lambda: "")

    @classmethod
    def from_env(cls) -> CriticAgentSettings:
        storage_path = os.environ.get("CKS_MCP_DB_PATH") or str(
            data_dir() / "cks_mcp.db"
        )
        return cls(
            poll_interval=float(
                os.environ.get("CKS_CRITIC_POLL_INTERVAL", _DEFAULT_POLL_INTERVAL_SECONDS)
            ),
            max_retries=int(
                os.environ.get("CKS_CRITIC_MAX_RETRIES", _DEFAULT_MAX_RETRIES)
            ),
            storage_path=storage_path,
        )


@dataclass(slots=True)
class Resolution:
    """The outcome of attempting to resolve one claimed conflict task."""

    resolved: bool
    detail: str | None = None


# ---------------------------------------------------------------------------
# Resolution policies
# ---------------------------------------------------------------------------


async def resolve_gossip_conflict(runtime: Runtime, task: dict[str, Any]) -> Resolution:
    """
    Attempt to resolve a ``gossip_conflict`` task via ``merge_branch``.

    ``task["session_id"]`` is the target session (the local replica's
    own session that ``GossipConflictDetected`` fired against);
    ``task["payload"]["source_session_id"]`` is the foreign branch
    already materialized locally by ``GossipAdapter``/
    ``register_foreign_branch`` (ADR-008) -- see
    ``list_gossip_conflicts``' own docstring for why no extra lookup
    is needed before passing it straight to ``merge_branch``.
    """
    payload = task.get("payload")
    if not isinstance(payload, dict):
        return Resolution(False, f"payload was not a JSON object: {payload!r}")

    source_session_id = payload.get("source_session_id")
    if not source_session_id:
        return Resolution(
            False,
            "payload has no 'source_session_id' -- cannot merge without knowing "
            "which branch to merge from.",
        )

    result = await merge_branch(
        runtime,
        {
            "target_session_id": task["session_id"],
            "source_session_id": source_session_id,
        },
    )

    if result.get("merged"):
        return Resolution(True)

    if "conflicts" in result:
        conflict_count = len(result["conflicts"])
        return Resolution(
            False,
            f"merge_branch reported {conflict_count} structural conflict(s) "
            "requiring explicit 'resolutions' -- this agent has no evidence "
            "to pick a side automatically.",
        )

    return Resolution(False, f"merge_branch did not succeed: {result}")


async def resolve_inference_conflict(runtime: Runtime, task: dict[str, Any]) -> Resolution:
    """
    Attempt to resolve an ``inference_conflict`` task via a single
    batch ``arbitrate_inference_conflict(auto_resolve=True, commit=True)``
    call covering every arbitrable diagnostic in the task's payload.
    """
    payload = task.get("payload")
    if not isinstance(payload, dict):
        return Resolution(False, f"payload was not a JSON object: {payload!r}")

    diagnostics = payload.get("diagnostics") or []
    conclusion_ids = sorted(
        {
            d.get("location")
            for d in diagnostics
            if isinstance(d, dict)
            and d.get("code") == _ARBITRABLE_DIAGNOSTIC_CODE
            and d.get("location")
        }
    )
    if not conclusion_ids:
        return Resolution(
            False,
            "no arbitrable conclusion_id found in diagnostics (only "
            f"{_ARBITRABLE_DIAGNOSTIC_CODE} diagnostics carry one -- e.g. a "
            "CKS-EXT-STALE-PREMISE-only finding has no arbitration primitive yet).",
        )

    result = await arbitrate_inference_conflict(
        runtime,
        {
            "session_id": task["session_id"],
            "conclusion_ids": conclusion_ids,
            "auto_resolve": True,
            "commit": True,
        },
    )

    if result.get("error"):
        return Resolution(False, f"arbitrate_inference_conflict error: {result}")

    results = result.get("results") or []
    unresolved = [
        item["conclusion_id"]
        for item in results
        if item.get("conflict") and "decision" not in item
    ]
    if unresolved:
        return Resolution(
            False,
            f"arbitrate_inference_conflict left {len(unresolved)} conclusion(s) "
            f"unresolved: {unresolved}",
        )

    if not result.get("commit_result"):
        # Every conclusion_id resolved to "conflict": False (nothing to
        # arbitrate after all, e.g. staleness cleared itself) -- there
        # was genuinely nothing to commit. Treat as resolved: the task
        # described a state that no longer needs action.
        return Resolution(True)

    commit_result = result["commit_result"]
    if isinstance(commit_result, dict) and commit_result.get("error"):
        return Resolution(False, f"commit failed: {commit_result}")

    return Resolution(True)


_RESOLVERS = {
    "gossip_conflict": resolve_gossip_conflict,
    "inference_conflict": resolve_inference_conflict,
}


# ---------------------------------------------------------------------------
# Claim -> resolve -> complete/fail/dead-letter, for one task
# ---------------------------------------------------------------------------


async def _process_one(
    runtime: Runtime, task_type: str, settings: CriticAgentSettings
) -> bool | None:
    """
    Claim and process at most one task of ``task_type``.

    Returns True if a task was claimed and processed (regardless of
    outcome), None if the queue was empty, or raises nothing -- an
    unsupported storage backend is reported via the return value of
    ``claim_conflict_task`` and logged once per call rather than
    raised, since it's a deployment condition (in-memory storage), not
    a bug.
    """
    claim_result = await claim_conflict_task(runtime, {"task_type": task_type})
    if not claim_result.get("supported"):
        print(
            f"[cks-critic-agent] storage backend does not support the "
            f"persistent outbox -- nothing to do for {task_type!r}. "
            "Configure a SQLite or Postgres CKS_MCP_DB_PATH.",
            file=sys.stderr,
        )
        return None

    task = claim_result.get("task")
    if task is None:
        return None

    resolver = _RESOLVERS[task_type]
    try:
        resolution = await resolver(runtime, task)
    except Exception as exc:  # noqa: BLE001 -- must never crash the loop
        resolution = Resolution(False, f"unexpected exception: {exc}")
        traceback.print_exc(file=sys.stderr)

    task_id = task["task_id"]
    if resolution.resolved:
        await complete_conflict_task(runtime, {"task_id": task_id})
        print(
            f"[cks-critic-agent] resolved {task_type} task_id={task_id} "
            f"session_id={task['session_id']}",
            file=sys.stderr,
        )
        return True

    error = resolution.detail or "unknown error"
    next_retry_count = task["retry_count"] + 1
    if next_retry_count >= settings.max_retries:
        await dead_letter_conflict_task(runtime, {"task_id": task_id, "error": error})
        print(
            f"[cks-critic-agent] dead-lettered {task_type} task_id={task_id} "
            f"after {next_retry_count} attempt(s): {error}",
            file=sys.stderr,
        )
    else:
        await fail_conflict_task(
            runtime,
            {"task_id": task_id, "retry_count": next_retry_count, "error": error},
        )
        print(
            f"[cks-critic-agent] retrying {task_type} task_id={task_id} "
            f"(attempt {next_retry_count}/{settings.max_retries}): {error}",
            file=sys.stderr,
        )
    return True


async def run_once(runtime: Runtime, settings: CriticAgentSettings | None = None) -> int:
    """
    Drain every currently-eligible task across both task types once
    (claiming one at a time per type until each queue reports empty),
    returning the total number of tasks processed. Used by the main
    loop's each iteration, and directly by tests / a one-shot CLI mode
    that doesn't want to poll forever.
    """
    settings = settings or CriticAgentSettings.from_env()
    processed = 0
    for task_type in _TASK_TYPES:
        while await _process_one(runtime, task_type, settings):
            processed += 1
    return processed


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def run_critic_agent(
    *,
    settings: CriticAgentSettings | None = None,
    max_iterations: int | None = None,
) -> None:
    """
    Construct this process' own ``Runtime`` (sharing storage with the
    main ``cks-mcp`` server via the same ``storage_path``) and loop:
    drain both conflict queues, sleep ``poll_interval``, repeat.

    ``max_iterations``, when given, stops the loop after that many
    poll cycles instead of running forever -- used by tests and by a
    supervisor that wants to restart the process periodically rather
    than trust a single long-lived event loop.
    """
    settings = settings or CriticAgentSettings.from_env()

    config = RuntimeConfig(storage_path=settings.storage_path)
    runtime = await Runtime.create(core=CksCoreAdapter(), config=config)

    stop = asyncio.Event()

    def _handle_signal(*_: Any) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except (NotImplementedError, RuntimeError):
            # Signal handlers aren't available on every platform/thread
            # (e.g. Windows, or when not running in the main thread of
            # the main interpreter) -- the loop still exits cleanly via
            # KeyboardInterrupt/task cancellation in that case, this is
            # just a nicer shutdown path where it's supported.
            pass

    print(
        f"[cks-critic-agent] started (storage_path={settings.storage_path!r}, "
        f"poll_interval={settings.poll_interval}s, max_retries={settings.max_retries})",
        file=sys.stderr,
    )

    try:
        iterations = 0
        while not stop.is_set():
            processed = await run_once(runtime, settings)
            if processed == 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=settings.poll_interval)
                except TimeoutError:
                    pass
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
    finally:
        await runtime.aclose()
        print("[cks-critic-agent] stopped", file=sys.stderr)


def main_sync() -> None:
    """Console-script entry point (see pyproject.toml's [project.scripts])."""
    asyncio.run(run_critic_agent())


if __name__ == "__main__":
    main_sync()
