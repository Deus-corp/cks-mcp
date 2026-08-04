"""
Critic Agent: an autonomous, unattended process that resolves gossip,
inference, provenance, and temporal conflicts from the persistent
outbox.

This is the "Critic Agent runtime loop" item from ROADMAP.md's "Next
Up" section -- the last missing piece of the Critic-agent design. All
of the supporting plumbing already shipped before this module:

- Detection: ``InferenceStalenessSweeper`` (cks-runtime, ADR-009),
  ``GossipConflictDetected`` (ADR-008), ``ProvenanceStalenessSweeper``
  (cks-runtime, ADR-010).
- Queueing: gossip/inference conflicts are dual-written into the
  persistent outbox (``cks_outbox_tasks``, task_type
  ``"gossip_conflict"``/``"inference_conflict"``) by
  ``cks_mcp.gossip``/``cks_mcp.observability`` whenever the storage
  backend supports it (SQLite or Postgres -- never the default
  in-memory backend). ``ProvenanceStalenessSweeper`` writes
  ``"provenance_conflict"`` tasks onto the same outbox directly, since
  detection there already lives in cks-runtime rather than cks-mcp.
- Claiming: ``claim_conflict_task`` atomically dequeues one task at a
  time from a *separate* Runtime/process, exactly what this module
  needs -- see that tool's own docstring for why a separate process
  can't just read the in-process ``ConflictInbox`` the interactive
  ``list_gossip_conflicts``/``list_inference_conflicts`` tools use.
- Resolution: ``merge_branch`` (gossip),
  ``arbitrate_inference_conflict`` with ``auto_resolve``+``commit``
  (inference), and ``refresh_verification`` with ``commit`` (provenance
  -- see that tool's own docstring for why it has no ``auto_resolve``
  LLM path).
- Outcome: ``complete_conflict_task`` / ``fail_conflict_task`` /
  ``dead_letter_conflict_task``.

This module is the loop that ties them together: it runs as its own
OS process with its *own* ``Runtime`` instance pointed at the same
persistent storage the main ``cks-mcp`` server uses (same SQLite file,
or the same Postgres DSN), polls all queues, and drives each task
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
- ``inference_conflict``: a task's payload can carry two unrelated
  diagnostic codes at once. ``CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT``
  diagnostics name a ``conclusion_id`` that's resolved via ONE batch
  ``arbitrate_inference_conflict(conclusion_ids=..., auto_resolve=True,
  commit=True)`` call, reusing that tool's own LLM provider dispatch
  (``CKS_LLM_PROVIDER`` etc. -- see that tool's docstring).
  ``CKS-EXT-STALE-PREMISE`` findings describe a different condition --
  a premise going stale, not two active steps disputing a conclusion
  -- and are resolved mechanically (no LLM) via a separate batch
  ``arbitrate_inference_conflict(stale_premise_ids=..., commit=True)``
  call. The two calls are kept separate because the tool itself
  rejects ``conclusion_ids`` and ``stale_premise_ids`` together in one
  call; a task containing both diagnostic types gets one call per
  type, and the task only completes once both parts succeed. A step
  that path genuinely can't fix (e.g. it names a step_id the session
  doesn't have) is not silently dropped -- it's reported in the
  ``Resolution``'s detail and, after enough retries, dead-lettered for
  a human to look at.
- ``provenance_conflict`` (ADR-010): a stale ``VerificationRecord``
  found by ``ProvenanceStalenessSweeper`` (cks-runtime) is resolved
  mechanically -- no LLM involved at all -- via
  ``refresh_verification(auto_resolve=True, commit=True)``, which
  re-runs the same real HTTP check ``verify_source`` performs and
  commits the fresh, signed record. A task whose subject carries no
  URL to re-check is dead-lettered for a human rather than retried.
- ``temporal_conflict`` (ADR-011): an expired ``valid_until`` found by
  ``TemporalStalenessSweeper`` (cks-runtime) is resolved via a safe
  default policy -- ``resolve_temporal_conflict(action="bump",
  extend_by_days=30, commit=True)`` -- rather than guessing whether
  the fact should instead be archived. A missing ``object_id`` in the
  payload, or an object that no longer exists (already resolved/
  removed by an earlier pass), is reported as a failure rather than
  silently dropped.

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
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from cks_runtime.config import RuntimeConfig
from cks_runtime.runtime import Runtime
from cks_runtime_plugins.cks_core import CksCoreAdapter

from cks_mcp.agent_loop import Resolution, run_resolver_with_heartbeat
from cks_mcp.paths import data_dir
from cks_mcp.tools.arbitrate_inference_conflict.handler import (
    arbitrate_inference_conflict,
)
from cks_mcp.tools.claim_conflict_task.handler import claim_conflict_task
from cks_mcp.tools.complete_conflict_task.handler import complete_conflict_task
from cks_mcp.tools.dead_letter_conflict_task.handler import dead_letter_conflict_task
from cks_mcp.tools.fail_conflict_task.handler import fail_conflict_task
from cks_mcp.tools.merge.handler import merge_branch
from cks_mcp.tools.refresh_verification.handler import refresh_verification
from cks_mcp.tools.resolve_temporal_conflict.handler import (
    resolve_temporal_conflict as _resolve_temporal_conflict_tool,
)

# Resolution/run_resolver_with_heartbeat now live in cks_mcp.agent_loop
# (shared with cks_mcp.enrichment_agent) -- re-exported under their
# original names here for backward compatibility (this module's own
# tests, and any external code, import them from cks_mcp.critic_agent).
_run_resolver_with_heartbeat = run_resolver_with_heartbeat

_ARBITRABLE_DIAGNOSTIC_CODE = "CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT"
_STALE_PREMISE_CODE = "CKS-EXT-STALE-PREMISE"

# Same backoff cap philosophy as OutboxEmbeddingWorker/fail_conflict_task:
# a conflict is dead-lettered rather than retried forever once it's
# failed this many times.
_DEFAULT_MAX_RETRIES = 5
_DEFAULT_POLL_INTERVAL_SECONDS = 5.0

# Must stay comfortably under SQLiteStorage's/PostgresStorage's stale-lease
# reclaim window (5 minutes) -- see _run_resolver_with_heartbeat.
_DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 60.0

# Consecutive LLM-attributable arbitration failures before the circuit
# breaker opens and auto_resolve calls are skipped for a cooldown period.
_DEFAULT_LLM_BREAKER_THRESHOLD = 3
_DEFAULT_LLM_BREAKER_COOLDOWN_SECONDS = 60.0

_TASK_TYPES = (
    "gossip_conflict",
    "inference_conflict",
    "provenance_conflict",
    "temporal_conflict",
)

# Default "bump" extension applied by resolve_temporal_conflict below --
# a safe default policy: if nobody has removed/superseded the fact, just
# give it more time rather than guessing it should be archived.
_TEMPORAL_BUMP_EXTEND_DAYS = 30


@dataclass(slots=True)
class CriticAgentSettings:
    """Runtime-tunable knobs for the Critic Agent loop, from env vars."""

    poll_interval: float = _DEFAULT_POLL_INTERVAL_SECONDS
    max_retries: int = _DEFAULT_MAX_RETRIES
    storage_path: str = field(default_factory=lambda: "")
    heartbeat_interval: float = _DEFAULT_HEARTBEAT_INTERVAL_SECONDS
    llm_breaker_threshold: int = _DEFAULT_LLM_BREAKER_THRESHOLD
    llm_breaker_cooldown: float = _DEFAULT_LLM_BREAKER_COOLDOWN_SECONDS

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
            heartbeat_interval=float(
                os.environ.get(
                    "CKS_CRITIC_HEARTBEAT_INTERVAL", _DEFAULT_HEARTBEAT_INTERVAL_SECONDS
                )
            ),
            llm_breaker_threshold=int(
                os.environ.get(
                    "CKS_CRITIC_LLM_BREAKER_THRESHOLD", _DEFAULT_LLM_BREAKER_THRESHOLD
                )
            ),
            llm_breaker_cooldown=float(
                os.environ.get(
                    "CKS_CRITIC_LLM_BREAKER_COOLDOWN", _DEFAULT_LLM_BREAKER_COOLDOWN_SECONDS
                )
            ),
        )


# ---------------------------------------------------------------------------
# Metrics (in-process; surfaced via get_metrics, see cks_mcp.observability)
# ---------------------------------------------------------------------------


@dataclass
class CriticAgentMetrics:
    """
    Critic-Agent-specific counters, kept in addition to the generic
    per-tool telemetry ``get_metrics`` already reports (calls/success_rate/
    latency say nothing about queue depth or dead-letter rate). Process-
    local -- a Critic Agent running as its own OS process only reports
    what it itself has seen since it started; there's no cross-process
    aggregation here.
    """

    processed: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    completed: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    retried: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    dead_lettered: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    lease_lost: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    llm_breaker_trips: int = 0
    llm_breaker_open: bool = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "processed": dict(self.processed),
            "completed": dict(self.completed),
            "retried": dict(self.retried),
            "dead_lettered": dict(self.dead_lettered),
            "lease_lost": dict(self.lease_lost),
            "llm_breaker_trips": self.llm_breaker_trips,
            "llm_breaker_open": self.llm_breaker_open,
        }

    def reset(self) -> None:
        self.processed.clear()
        self.completed.clear()
        self.retried.clear()
        self.dead_lettered.clear()
        self.lease_lost.clear()
        self.llm_breaker_trips = 0
        self.llm_breaker_open = False


_METRICS = CriticAgentMetrics()


def get_critic_metrics() -> dict[str, Any]:
    """
    Snapshot of this process' Critic Agent metrics, for ``get_metrics``
    (see ``cks_mcp.observability``) or direct inspection. Returns zeros
    for every counter if no Critic Agent has processed anything in this
    process yet -- this does not query the outbox table itself, so it's
    silent about tasks another process (e.g. a second Critic Agent
    worker) has handled.
    """
    return _METRICS.snapshot()


# ---------------------------------------------------------------------------
# LLM circuit breaker (guards auto_resolve, not the mechanical
# stale-premise path, which never calls an LLM)
# ---------------------------------------------------------------------------

# Error codes arbitrate_inference_conflict attaches to a batch item when
# the LLM call itself (not the conflict data) is why no decision was
# reached -- see that tool's handler.py. Used to tell "the provider is
# down" apart from "this particular conflict is unresolvable", so the
# breaker only trips on the former.
_LLM_ATTRIBUTABLE_ERROR_CODES = frozenset(
    {"internal_error", "llm_output_parse_error", "invalid_arbiter_decision", "missing_decision"}
)


class LLMCircuitBreaker:
    """
    Trips after ``threshold`` consecutive LLM-attributable arbitration
    failures and, while open, makes ``_resolve_confidence_conflicts``
    skip the ``arbitrate_inference_conflict(auto_resolve=True, ...)``
    call entirely for ``cooldown`` seconds -- instead of burning an LLM
    call (and a retry/backoff cycle) per queued task while the provider
    is down. The mechanical ``stale_premise_ids`` path never calls an
    LLM and is unaffected by this breaker's state.
    """

    def __init__(
        self,
        threshold: int = _DEFAULT_LLM_BREAKER_THRESHOLD,
        cooldown: float = _DEFAULT_LLM_BREAKER_COOLDOWN_SECONDS,
    ) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self._consecutive_failures = 0
        self._open_until: float = 0.0

    def is_open(self) -> bool:
        if self._open_until and time.monotonic() < self._open_until:
            return True
        if self._open_until:
            # Cooldown elapsed -- half-open: let the next call through as
            # a trial rather than staying open forever.
            self._open_until = 0.0
            _METRICS.llm_breaker_open = False
        return False

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._open_until = 0.0
        _METRICS.llm_breaker_open = False

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.threshold:
            self._open_until = time.monotonic() + self.cooldown
            _METRICS.llm_breaker_trips += 1
            _METRICS.llm_breaker_open = True

    def configure(self, *, threshold: int, cooldown: float) -> None:
        """Apply settings without losing accumulated failure state."""
        self.threshold = threshold
        self.cooldown = cooldown


# Module-level singleton: one Critic Agent process, one breaker, shared
# across every _resolve_confidence_conflicts call in that process.
_LLM_BREAKER = LLMCircuitBreaker()


def reset_critic_agent_state() -> None:
    """Reset global metrics and breaker state -- for tests only."""
    _METRICS.reset()
    _LLM_BREAKER._consecutive_failures = 0
    _LLM_BREAKER._open_until = 0.0


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


async def resolve_provenance_conflict(runtime: Runtime, task: dict[str, Any]) -> Resolution:
    """
    Attempt to resolve a ``provenance_conflict`` task (ADR-010,
    ``ProvenanceStalenessSweeper`` in cks-runtime) via
    ``refresh_verification(auto_resolve=True, commit=True)``.

    The task's payload is the sweeper's own escalation shape:
    ``{"record_id", "subject_id", "source_url", "checked_at", "reason"}``
    (see ``ProvenanceStalenessSweeper._sweep_session``). ``source_url``
    can legitimately be absent -- the sweeper only includes it when the
    VerificationRecord's subject happens to carry a ``url`` field (e.g.
    a ``Document``) -- in which case there is nothing for this agent to
    re-check automatically, and the task is dead-lettered for a human
    (not retried: a missing URL on the subject won't appear on a later
    attempt).

    Unlike ``resolve_inference_conflict``, there is no LLM circuit
    breaker to guard here: ``refresh_verification`` never calls an LLM
    (see that tool's own docstring), so there is no provider outage
    for a breaker to protect against.
    """
    payload = task.get("payload")
    if not isinstance(payload, dict):
        return Resolution(False, f"payload was not a JSON object: {payload!r}")

    record_id = payload.get("record_id")
    subject_id = payload.get("subject_id")
    source_url = payload.get("source_url")

    if not record_id or not subject_id:
        return Resolution(
            False,
            "payload is missing 'record_id' and/or 'subject_id' -- cannot "
            "refresh a verification without knowing which record/subject "
            "it belongs to.",
        )
    if not source_url:
        return Resolution(
            False,
            f"payload has no 'source_url' for subject_id={subject_id!r} -- "
            "the subject carries no 'url' field, so there is nothing for "
            "this agent to re-check automatically.",
        )

    result = await refresh_verification(
        runtime,
        {
            "session_id": task["session_id"],
            "record_id": record_id,
            "subject_id": subject_id,
            "source_url": source_url,
            "auto_resolve": True,
            "commit": True,
        },
    )

    if result.get("error"):
        return Resolution(False, f"refresh_verification error: {result}")

    commit_result = result.get("commit_result")
    if isinstance(commit_result, dict) and commit_result.get("error"):
        return Resolution(False, f"commit failed: {commit_result}")

    return Resolution(True)


async def resolve_temporal_conflict(runtime: Runtime, task: dict[str, Any]) -> Resolution:
    """
    Attempt to resolve a ``temporal_conflict`` task (ADR-011,
    ``TemporalStalenessSweeper`` in cks-runtime) via
    ``resolve_temporal_conflict(action="bump", extend_by_days=30,
    commit=True)``.

    The task's payload is the sweeper's own escalation shape (at
    minimum ``{"object_id"}`` -- see
    ``TemporalStalenessSweeper._sweep_session``). Unlike
    ``resolve_provenance_conflict``'s single mechanical remedy, an
    expired ``valid_until`` has no single canonical fix (bump/archive/
    ignore are all legitimate depending on domain knowledge this agent
    doesn't have) -- but "bump 30 days" is a safe default: if the fact
    is genuinely still true, extending it costs nothing, and if it
    should actually be archived a human/future policy can still catch
    it via ``resolve_temporal_conflict``'s other actions. This mirrors
    the "own policy" half of the Critic Agent design rather than
    guessing which of ``archive``/``ignore`` is correct with no
    evidence either way.

    Like ``resolve_provenance_conflict``, there is no LLM circuit
    breaker to guard here: the underlying ``resolve_temporal_conflict``
    tool is purely mechanical (one ``update_object`` via
    ``evolve_knowledge``), never calls an LLM.
    """
    payload = task.get("payload")
    if not isinstance(payload, dict):
        return Resolution(False, f"payload was not a JSON object: {payload!r}")

    object_id = payload.get("object_id")
    if not object_id:
        return Resolution(
            False,
            "payload has no 'object_id' -- cannot bump a valid_until without "
            "knowing which object it belongs to.",
        )

    result = await _resolve_temporal_conflict_tool(
        runtime,
        {
            "session_id": task["session_id"],
            "object_id": object_id,
            "action": "bump",
            "extend_by_days": _TEMPORAL_BUMP_EXTEND_DAYS,
            "commit": True,
        },
    )

    if result.get("error"):
        return Resolution(False, f"resolve_temporal_conflict error: {result}")

    commit_result = result.get("commit_result")
    if isinstance(commit_result, dict) and commit_result.get("error"):
        return Resolution(False, f"commit failed: {commit_result}")

    return Resolution(True)


def _extract_locations(diagnostics: list[Any], code: str) -> list[str]:
    return sorted(
        {
            loc
            for d in diagnostics
            if isinstance(d, dict) and d.get("code") == code
            for loc in [d.get("location")]
            if loc
        }
    )


async def _resolve_confidence_conflicts(
    runtime: Runtime,
    session_id: str,
    conclusion_ids: list[str],
    breaker: LLMCircuitBreaker | None = None,
) -> Resolution:
    """
    Resolve every ``CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT`` finding in
    one batch ``arbitrate_inference_conflict(conclusion_ids=...,
    auto_resolve=True, commit=True)`` call.

    Guarded by ``breaker`` (the module's shared ``_LLM_BREAKER`` unless
    a caller passes its own, e.g. in tests): if the breaker is open,
    this returns a failed ``Resolution`` without making the call at
    all, so a downed LLM provider doesn't cost one LLM call per queued
    task on top of the outage itself.
    """
    breaker = breaker if breaker is not None else _LLM_BREAKER
    if breaker.is_open():
        return Resolution(
            False,
            "LLM circuit breaker open (repeated arbiter failures) -- skipping "
            f"auto_resolve for {len(conclusion_ids)} conclusion(s) until cooldown elapses",
        )

    result = await arbitrate_inference_conflict(
        runtime,
        {
            "session_id": session_id,
            "conclusion_ids": conclusion_ids,
            "auto_resolve": True,
            "commit": True,
        },
    )

    if result.get("error"):
        # Structural error (invalid_parameter, session_not_found, ...) --
        # not the LLM provider's fault, so this doesn't affect the breaker.
        return Resolution(False, f"arbitrate_inference_conflict (conclusion_ids) error: {result}")

    results = result.get("results") or []
    unresolved = [
        item["conclusion_id"]
        for item in results
        if item.get("conflict") and "decision" not in item
    ]
    if unresolved:
        llm_attributable = any(
            item.get("conclusion_id") in unresolved and item.get("error") in _LLM_ATTRIBUTABLE_ERROR_CODES
            for item in results
        )
        if llm_attributable:
            breaker.record_failure()
        return Resolution(
            False,
            f"arbitrate_inference_conflict left {len(unresolved)} conclusion(s) "
            f"unresolved: {unresolved}",
        )

    if not result.get("commit_result"):
        # Every conclusion_id resolved to "conflict": False (nothing to
        # arbitrate after all, e.g. staleness cleared itself) -- there
        # was genuinely nothing to commit. Treat as resolved: the task
        # described a state that no longer needs action. Doesn't touch
        # the breaker -- no LLM call was actually needed or made.
        return Resolution(True)

    commit_result = result["commit_result"]
    if isinstance(commit_result, dict) and commit_result.get("error"):
        return Resolution(False, f"commit failed: {commit_result}")

    breaker.record_success()
    return Resolution(True)


async def _resolve_stale_premises(
    runtime: Runtime, session_id: str, stale_step_ids: list[str]
) -> Resolution:
    """
    Resolve every ``CKS-EXT-STALE-PREMISE`` finding via the mechanical
    (no-LLM) ``arbitrate_inference_conflict(stale_premise_ids=...,
    commit=True)`` path, instead of silently discarding the task.
    """
    result = await arbitrate_inference_conflict(
        runtime,
        {
            "session_id": session_id,
            "stale_premise_ids": stale_step_ids,
            "commit": True,
        },
    )

    if result.get("error"):
        return Resolution(False, f"arbitrate_inference_conflict (stale_premise_ids) error: {result}")

    results = result.get("results") or []
    failed = [
        item.get("step_id")
        for item in results
        if item.get("error") is not None
    ]
    if failed:
        return Resolution(
            False,
            f"arbitrate_inference_conflict could not resolve {len(failed)} "
            f"stale premise step(s): {failed}",
        )

    commit_result = result.get("commit_result")
    if isinstance(commit_result, dict) and commit_result.get("error"):
        return Resolution(False, f"commit failed: {commit_result}")

    # No commit_result means every step either had no stale premises
    # left to fix (nothing to do -- fine) or was never given operations
    # to run; either way there was no per-step 'error', so this counts
    # as resolved.
    return Resolution(True)


async def resolve_inference_conflict(runtime: Runtime, task: dict[str, Any]) -> Resolution:
    """
    Attempt to resolve an ``inference_conflict`` task.

    The task's payload can carry two unrelated diagnostic codes at
    once (``InferenceStalenessSweeper`` bundles whatever it found in
    one sweep into a single event/payload): confidence conflicts
    (``CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT``) and stale premises
    (``CKS-EXT-STALE-PREMISE``). ``arbitrate_inference_conflict``
    treats these as mutually exclusive -- passing both
    ``conclusion_ids`` and ``stale_premise_ids`` in one call is
    rejected with an ``invalid_parameter`` error -- so each diagnostic
    type is resolved via its own, independent call, and the two
    outcomes are combined below. This also means a payload made up of
    stale-premise findings only, with no confidence conflicts, is
    genuinely repaired (via the mechanical ``stale_premise_ids`` path)
    instead of just being marked complete with nothing done.
    """
    payload = task.get("payload")
    if not isinstance(payload, dict):
        return Resolution(False, f"payload was not a JSON object: {payload!r}")

    diagnostics = payload.get("diagnostics") or []
    conclusion_ids = _extract_locations(diagnostics, _ARBITRABLE_DIAGNOSTIC_CODE)
    stale_step_ids = _extract_locations(diagnostics, _STALE_PREMISE_CODE)

    if not conclusion_ids and not stale_step_ids:
        return Resolution(
            True,  # nothing arbitrable in this payload
            "no CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT or CKS-EXT-STALE-PREMISE "
            "diagnostics in payload",
        )

    session_id = task["session_id"]
    details: list[str] = []
    resolved = True

    if conclusion_ids:
        confidence_resolution = await _resolve_confidence_conflicts(
            runtime, session_id, conclusion_ids
        )
        resolved = resolved and confidence_resolution.resolved
        if confidence_resolution.detail:
            details.append(confidence_resolution.detail)

    if stale_step_ids:
        stale_resolution = await _resolve_stale_premises(runtime, session_id, stale_step_ids)
        resolved = resolved and stale_resolution.resolved
        if stale_resolution.detail:
            details.append(stale_resolution.detail)

    return Resolution(resolved, "; ".join(details) if details else None)


_RESOLVERS = {
    "gossip_conflict": resolve_gossip_conflict,
    "inference_conflict": resolve_inference_conflict,
    "provenance_conflict": resolve_provenance_conflict,
    "temporal_conflict": resolve_temporal_conflict,
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

    task_id = task["task_id"]
    _METRICS.processed[task_type] += 1

    resolver = _RESOLVERS[task_type]
    try:
        resolution, lease_lost = await _run_resolver_with_heartbeat(
            runtime, resolver, task, task_id, settings.heartbeat_interval
        )
    except Exception as exc:  # noqa: BLE001 -- must never crash the loop
        resolution = Resolution(False, f"unexpected exception: {exc}")
        lease_lost = False
        traceback.print_exc(file=sys.stderr)

    if lease_lost:
        _METRICS.lease_lost[task_type] += 1
        print(
            f"[cks-critic-agent] lost lease on {task_type} task_id={task_id} while "
            "resolving (reclaimed by another worker) -- abandoning without "
            "completing/failing/dead-lettering it",
            file=sys.stderr,
        )
        return True

    if resolution.resolved:
        await complete_conflict_task(runtime, {"task_id": task_id})
        _METRICS.completed[task_type] += 1
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
        _METRICS.dead_lettered[task_type] += 1
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
        _METRICS.retried[task_type] += 1
        print(
            f"[cks-critic-agent] retrying {task_type} task_id={task_id} "
            f"(attempt {next_retry_count}/{settings.max_retries}): {error}",
            file=sys.stderr,
        )
    return True


async def run_once(runtime: Runtime, settings: CriticAgentSettings | None = None) -> int:
    """
    Drain every currently-eligible task across every task type once
    (claiming one at a time per type until each queue reports empty),
    returning the total number of tasks processed. Used by the main
    loop's each iteration, and directly by tests / a one-shot CLI mode
    that doesn't want to poll forever.
    """
    settings = settings or CriticAgentSettings.from_env()
    _LLM_BREAKER.configure(
        threshold=settings.llm_breaker_threshold, cooldown=settings.llm_breaker_cooldown
    )
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
    drain all conflict queues, sleep ``poll_interval``, repeat.

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
        f"poll_interval={settings.poll_interval}s, max_retries={settings.max_retries}, "
        f"heartbeat_interval={settings.heartbeat_interval}s, "
        f"llm_breaker_threshold={settings.llm_breaker_threshold}, "
        f"llm_breaker_cooldown={settings.llm_breaker_cooldown}s)",
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