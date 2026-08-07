"""
Fork Resolution Agent: an autonomous, unattended process that resolves
CRDT MV-Register forks (ADR-013, Stage 2 -- ``crdt_fork`` conflict
events) without human involvement.

This is the "Stage 3" piece of the CRDT roadmap: Stage 1 (``cks-runtime``)
gave every replica a G-Set + Merkle tree; Stage 2 added the MV-Register,
fork detection (``CRDTForkDetected``), and ``cks_mcp.conflict_inbox``/
``cks_mcp.gossip`` wiring to surface forks for review. This module is
the loop that actually clears them, following the exact same
claim -> resolve -> complete/fail/dead-letter pattern already used by
``cks_mcp.critic_agent`` and ``cks_mcp.enrichment_agent`` (both built on
the shared ``cks_mcp.agent_loop`` helpers) -- but run as its own,
dedicated console script/process rather than folded into the Critic
Agent's own ``crdt_fork`` handling.

.. note::
   ``cks_mcp.critic_agent`` already claims and resolves ``crdt_fork``
   tasks too (see its own ``resolve_crdt_fork``), using a *different*
   deterministic policy (always keep the lexicographically-*last*
   object_id, with no VersionVector/created_at comparison). Both
   agents poll the exact same ``cks_outbox_tasks`` queue
   (``task_type="crdt_fork"``) via ``claim_conflict_task``, and a task
   claimed by one is atomically unavailable to the other -- so running
   both at once means whichever process happens to claim a given fork
   first decides its outcome, non-deterministically, per fork. This
   agent is meant to *replace* the Critic Agent's own crdt_fork
   handling operationally (run one or the other for that task_type,
   not both), not to run alongside it. See README.md's "Fork
   Resolution Agent" section.

Resolution policy (deliberately mechanical, no LLM -- same "own
policy" philosophy as ``resolve_temporal_conflict``/
``resolve_contradiction_conflict`` in the Critic Agent):

1. Load every still-existing ``KnowledgeObject`` named by the fork's
   ``conflicting_object_ids`` via ``CRDTStore.get_object``. An id that
   no longer exists (already collapsed by a prior partial resolution)
   is dropped from consideration rather than treated as an error.
2. If a single causally-*newer* object remains -- i.e. one candidate's
   ``VersionVector`` strictly dominates every other candidate's, per
   ``cks_runtime.crdt.causality.causality_check`` -- that candidate
   wins. This is the only step that reflects genuine causal history;
   the rest are tie-breaks for genuinely concurrent writes.
3. Otherwise (the vectors are causally concurrent, so there is no
   "newer" one by causality alone), fall back to each candidate's
   ``created_at`` timestamp on the live MV-Register pointer row and
   keep the most recently-written one.
4. If timestamps are also identical (or unavailable), fall back to a
   fully deterministic, replica-agnostic tie-break: the
   alphabetically-*first* object_id among the remaining candidates.
   Every object_id is a content hash computed identically by every
   replica (``crdt_store.object_id_for``), so this guarantees every
   replica's Fork Resolution Agent converges on the exact same winner
   independently, with no coordination required.

A task is dead-lettered (not retried forever) once its retry_count
would reach ``max_retries`` (default 3) -- a fork this agent still
can't resolve after that many attempts (e.g. the storage backend has
no attached CRDTStore) is treated as needing a human/operator, not
another identical retry.
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
from cks_runtime.crdt.causality import DOMINATES, EQUAL, causality_check
from cks_runtime.crdt.version_vector import VersionVector
from cks_runtime.runtime import Runtime
from cks_runtime_plugins.cks_core import CksCoreAdapter

from cks_mcp.agent_loop import Resolution, run_resolver_with_heartbeat
from cks_mcp.lca_arbiter import resolve_with_lca
from cks_mcp.paths import data_dir
from cks_mcp.tools.claim_conflict_task.handler import claim_conflict_task
from cks_mcp.tools.complete_conflict_task.handler import complete_conflict_task
from cks_mcp.tools.dead_letter_conflict_task.handler import dead_letter_conflict_task
from cks_mcp.tools.evolve.handler import evolve_knowledge
from cks_mcp.tools.fail_conflict_task.handler import fail_conflict_task

# Re-exported under its original name for symmetry with
# cks_mcp.critic_agent's own re-export -- this module's tests (and any
# external code) can import either name from here.
_run_resolver_with_heartbeat = run_resolver_with_heartbeat

_TASK_TYPE = "crdt_fork"

_DEFAULT_POLL_INTERVAL_SECONDS = 30.0
_DEFAULT_MAX_RETRIES = 3

# Must stay comfortably under SQLiteStorage's/PostgresStorage's stale-lease
# reclaim window (5 minutes) -- same reasoning as CriticAgentSettings.
_DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 60.0


@dataclass(slots=True)
class ForkResolutionAgentSettings:
    """Runtime-tunable knobs for the Fork Resolution Agent loop, from env vars."""

    poll_interval: float = _DEFAULT_POLL_INTERVAL_SECONDS
    max_retries: int = _DEFAULT_MAX_RETRIES
    storage_path: str = field(default_factory=lambda: "")
    heartbeat_interval: float = _DEFAULT_HEARTBEAT_INTERVAL_SECONDS
    # Whether to try the topology-aware LCA arbiter (cks_mcp.lca_arbiter)
    # before falling back to the mechanical VersionVector/created_at/
    # alphabetical policy below. Defaults to on -- the LCA path is a
    # pure best-effort addition: whenever it can't find a common
    # ancestor for the conflicting objects (e.g. they don't both live
    # in any currently-registered session's graph, or genuinely share
    # none), or the conflict is a "competing_claims" one it correctly
    # declines to auto-pick a winner for, resolution falls straight
    # through to the exact same mechanical policy as before.
    use_lca: bool = True

    @classmethod
    def from_env(cls) -> ForkResolutionAgentSettings:
        storage_path = os.environ.get("CKS_MCP_DB_PATH") or str(
            data_dir() / "cks_mcp.db"
        )
        return cls(
            poll_interval=float(
                os.environ.get(
                    "CKS_FORK_AGENT_POLL_INTERVAL", _DEFAULT_POLL_INTERVAL_SECONDS
                )
            ),
            max_retries=int(
                os.environ.get("CKS_FORK_AGENT_MAX_RETRIES", _DEFAULT_MAX_RETRIES)
            ),
            storage_path=storage_path,
            heartbeat_interval=float(
                os.environ.get(
                    "CKS_FORK_AGENT_HEARTBEAT_INTERVAL",
                    _DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
                )
            ),
            use_lca=os.environ.get("CKS_FORK_AGENT_USE_LCA", "1") not in ("0", "false", "False"),
        )


# ---------------------------------------------------------------------------
# CRDTStore lookup
# ---------------------------------------------------------------------------


def _crdt_store_for(runtime: Runtime) -> Any | None:
    """
    Build a ``CRDTStore`` wrapping ``runtime.storage``'s own connection.

    Deliberately duplicated (not imported) from
    ``cks_mcp.gossip._build_crdt_store``/``cks_mcp.critic_agent._crdt_store_for``
    -- same reasoning as the latter's own docstring: this module must be
    able to resolve ``crdt_fork`` tasks as a standalone process even
    when started against a backend where the optional gossip subsystem
    was never enabled in *this* process; the forks it drains were
    written by some other process's gossip-enabled adapter, sharing
    the same underlying storage.
    """
    from cks_runtime.storage.sqlite_storage import SQLiteStorage

    storage = runtime.storage
    storage = getattr(storage, "wrapped", storage)
    if isinstance(storage, SQLiteStorage):
        from cks_runtime.crdt.crdt_store import SQLiteCRDTStore

        conn = getattr(storage, "_conn", None)
        if conn is None:
            return None
        # Share storage's own RLock, not just its connection -- see
        # `cks_mcp.gossip._build_crdt_store`'s comment on the same
        # line and `SQLiteCRDTStore._synchronized`'s docstring for why
        # an independent lock wouldn't actually serialize access to
        # the shared connection.
        lock = getattr(storage, "_lock", None)
        return SQLiteCRDTStore(conn, lock=lock)

    try:
        from cks_runtime.storage.postgres_storage import PostgresStorage
    except ImportError:
        return None

    if isinstance(storage, PostgresStorage):
        from cks_runtime.crdt.crdt_store import PostgresCRDTStore

        pool = getattr(storage, "_pool", None)
        return PostgresCRDTStore(pool) if pool is not None else None

    return None


async def _maybe_await(value: Any) -> Any:
    """Await ``value`` if it's awaitable (Postgres backend), else return it as-is (SQLite)."""
    if hasattr(value, "__await__"):
        return await value
    return value


# ---------------------------------------------------------------------------
# Winner selection
# ---------------------------------------------------------------------------


def _find_causally_newest(candidates: list[dict[str, Any]]) -> str | None:
    """
    Return the object_id whose ``VersionVector`` strictly dominates (or
    equals) every other candidate's, with at least one strict
    dominance relation among the comparisons -- i.e. a genuine,
    unambiguous "causally newer" winner. Returns None if no such
    candidate exists (the vectors are pairwise concurrent, or there
    are fewer than two candidates left to compare).
    """
    if len(candidates) < 2:
        return candidates[0]["object_id"] if candidates else None

    for candidate in candidates:
        others = [c for c in candidates if c is not candidate]
        relations = [causality_check(candidate["vv"], other["vv"]) for other in others]
        if all(relation in (DOMINATES, EQUAL) for relation in relations) and any(
            relation == DOMINATES for relation in relations
        ):
            return candidate["object_id"]

    return None


def _select_winner(candidates: list[dict[str, Any]]) -> str:
    """
    Pick a winning object_id among ``candidates`` (each a dict with
    ``object_id``, ``vv`` (``VersionVector``), and ``created_at``
    (``str | None``)), per this module's resolution policy: causal
    dominance first, then most-recent ``created_at``, then a
    deterministic alphabetical tie-break. Never raises -- always
    returns exactly one of the input object_ids.
    """
    newest = _find_causally_newest(candidates)
    if newest is not None:
        return newest

    timestamped = {c["object_id"]: c["created_at"] for c in candidates if c["created_at"]}
    if len(set(timestamped.values())) > 1:
        # ISO-8601 timestamps sort lexicographically == chronologically.
        # object_id is a tiebreaker within max() itself for identical
        # timestamps, keeping the choice deterministic either way.
        return max(timestamped, key=lambda oid: (timestamped[oid], oid))

    return min(c["object_id"] for c in candidates)


# ---------------------------------------------------------------------------
# LCA arbiter integration (optional, tried before the mechanical policy)
# ---------------------------------------------------------------------------


def _find_owning_session_id(runtime: Runtime, object_id_a: str, object_id_b: str) -> str | None:
    """
    Find a currently-registered ``RuntimeSession`` whose Knowledge Graph
    contains *both* conflicting object ids, so the LCA arbiter has a
    graph to analyze the topology of.

    CRDT forks (unlike session-scoped conflicts such as
    ``gossip_conflict``) have no session of their own -- ``fork_event``
    only carries the MV-Register ``pointer_key`` (see ``resolve_fork``'s
    docstring) -- so this is a best-effort lookup across every session
    this process currently has active, not a guaranteed one. Returns
    ``None`` if no such session is found (a fresh/never-materialized
    fork, a session closed since the fork occurred, or a process that
    never registered the relevant session at all), in which case the
    caller should fall back to the mechanical policy.
    """
    for session in runtime.list_sessions():
        structure = session.knowledge_structure
        if object_id_a in structure and object_id_b in structure:
            return session.session_id
    return None


async def _try_lca_resolution(
    runtime: Runtime, existing_ids: list[str]
) -> tuple[str | None, str | None]:
    """
    Attempt LCA-based arbitration across every pair of ``existing_ids``
    (almost always exactly two, but the fork payload's
    ``conflicting_object_ids`` list is not itself bounded to two).

    Returns ``(winner_object_id, detail)``. ``winner_object_id`` is
    ``None`` whenever the LCA arbiter has nothing conclusive to offer
    for *any* pair -- no owning session found, no common ancestor, or a
    genuine "competing_claims" needing human/Critic arbitration -- in
    which case the caller falls back to the mechanical policy
    unchanged. Never raises: any failure degrades to
    ``(None, <reason>)``.

    A resolution object recording the LCA arbiter's decision (see
    ``lca_arbiter._build_resolution_object``) is committed into the
    owning session via ``evolve_knowledge`` whenever one is produced,
    win or not, so the rationale is auditable in the graph regardless
    of whether this function ends up picking a winner.
    """
    if len(existing_ids) < 2:
        return None, "fewer than two candidates; nothing to arbitrate"

    for i in range(len(existing_ids)):
        for j in range(i + 1, len(existing_ids)):
            object_id_a, object_id_b = existing_ids[i], existing_ids[j]
            session_id = _find_owning_session_id(runtime, object_id_a, object_id_b)
            if session_id is None:
                continue

            try:
                lca_resolution = await resolve_with_lca(
                    runtime, session_id, object_id_a, object_id_b
                )
            except Exception as exc:  # noqa: BLE001 -- LCA path is best-effort
                print(
                    f"[cks-fork-agent] LCA arbiter raised for "
                    f"({object_id_a}, {object_id_b}): {exc}; falling back to "
                    "mechanical policy",
                    file=sys.stderr,
                )
                continue

            if not lca_resolution.resolved:
                continue

            if lca_resolution.resolution_object is not None:
                await evolve_knowledge(
                    runtime,
                    {
                        "session_id": session_id,
                        "operations": [
                            {
                                "type": "add_object",
                                "identity": lca_resolution.resolution_object["identity"],
                                "structure": lca_resolution.resolution_object["structure"],
                            }
                        ],
                    },
                )

            if lca_resolution.winner_object_id is not None:
                return lca_resolution.winner_object_id, lca_resolution.detail

            # "non_overlapping" (both kept) or "competing_claims" (needs
            # a human/Critic to act on the recorded Resolution Object)
            # -- either way, no single mechanical winner to report yet.

    return None, "LCA arbiter found no conclusive winner for any candidate pair"


# ---------------------------------------------------------------------------
# Resolution policy
# ---------------------------------------------------------------------------


async def resolve_fork(runtime: Runtime, fork_event: dict[str, Any]) -> Resolution:
    """
    Attempt to resolve one ``crdt_fork`` task claimed from the outbox.

    ``fork_event["session_id"]`` carries the MV-Register ``pointer_key``
    that forked (``crdt_fork`` tasks are enqueued with the pointer_key
    in that slot -- see ``cks_mcp.gossip``'s ``_on_fork`` -- since a
    CRDT fork has no session of its own to key by).
    ``fork_event["payload"]`` carries ``pointer_key``,
    ``conflicting_object_ids``, and ``event_id`` (the matching
    ``cks_conflict_events`` row).
    """
    payload = fork_event.get("payload")
    if not isinstance(payload, dict):
        return Resolution(False, f"payload was not a JSON object: {payload!r}")

    pointer_key = payload.get("pointer_key") or fork_event.get("session_id")
    conflicting_object_ids = payload.get("conflicting_object_ids")
    event_id = payload.get("event_id")

    if not pointer_key:
        return Resolution(False, "payload has no 'pointer_key' to resolve.")
    if not isinstance(conflicting_object_ids, list) or len(conflicting_object_ids) < 2:
        return Resolution(
            False,
            "payload's 'conflicting_object_ids' must list 2+ object ids, got: "
            f"{conflicting_object_ids!r}",
        )

    crdt_store = _crdt_store_for(runtime)
    if crdt_store is None:
        return Resolution(
            False,
            "this Runtime's storage backend has no attached CRDTStore "
            "(InMemoryStorage, or ADR-013 Stage 2 gossip wiring not enabled).",
        )

    async def _mark_resolved() -> None:
        if event_id:
            await _maybe_await(crdt_store.mark_fork_resolved(event_id))

    # Step 1: load every candidate KnowledgeObject, dropping ids that
    # no longer exist (already collapsed by a prior partial pass).
    existing_ids: list[str] = []
    for object_id in conflicting_object_ids:
        knowledge_object = await _maybe_await(crdt_store.get_object(object_id))
        if knowledge_object is not None:
            existing_ids.append(object_id)

    if len(existing_ids) == 0:
        # Every candidate object is gone -- nothing left to arbitrate,
        # and no id survives to collapse the pointer onto.
        await _mark_resolved()
        return Resolution(True, "no candidate objects still exist; nothing to arbitrate")

    if len(existing_ids) == 1:
        resolved = await _maybe_await(
            crdt_store.resolve_pointer(pointer_key, existing_ids[0])
        )
        if not resolved:
            return Resolution(
                False,
                f"resolve_pointer('{pointer_key}', '{existing_ids[0]}') found no "
                "such object_id -- pointer may already have converged elsewhere.",
            )
        await _mark_resolved()
        return Resolution(True, "only one candidate object still exists; no-op winner")

    # Step 2-4: gather VersionVector + created_at from the live
    # MV-Register pointer rows (re-read live, not trusted from the
    # payload's snapshot, since a later update_pointer call may have
    # already resolved part of the fork by the time this task runs)
    # and pick a winner.
    pointers = await _maybe_await(crdt_store.get_pointers(pointer_key))
    pointer_by_object_id = {p["object_id"]: p for p in pointers}

    candidates = [
        {
            "object_id": object_id,
            "vv": VersionVector.from_dict(
                pointer_by_object_id[object_id]["vector_clock"]
            )
            if object_id in pointer_by_object_id
            else VersionVector(),
            "created_at": pointer_by_object_id.get(object_id, {}).get("created_at"),
        }
        for object_id in existing_ids
    ]

    winner = _select_winner(candidates)

    resolved = await _maybe_await(crdt_store.resolve_pointer(pointer_key, winner))
    if not resolved:
        return Resolution(
            False, f"resolve_pointer('{pointer_key}', '{winner}') found no such object_id"
        )

    await _mark_resolved()
    return Resolution(True)


# ---------------------------------------------------------------------------
# Claim -> resolve -> complete/fail/dead-letter, for one task
# ---------------------------------------------------------------------------


async def _process_one(runtime: Runtime, settings: ForkResolutionAgentSettings) -> bool | None:
    """
    Claim and process at most one ``crdt_fork`` task. Returns True if a
    task was claimed and processed (regardless of outcome), or None if
    the queue was empty / the backend doesn't support the outbox.
    """
    claim_result = await claim_conflict_task(runtime, {"task_type": _TASK_TYPE})
    if not claim_result.get("supported"):
        print(
            "[cks-fork-agent] storage backend does not support the persistent "
            "outbox -- nothing to do. Configure a SQLite or Postgres "
            "CKS_MCP_DB_PATH.",
            file=sys.stderr,
        )
        return None

    task = claim_result.get("task")
    if task is None:
        return None

    task_id = task["task_id"]

    try:
        resolution, lease_lost = await _run_resolver_with_heartbeat(
            runtime, resolve_fork, task, task_id, settings.heartbeat_interval
        )
    except Exception as exc:  # noqa: BLE001 -- must never crash the loop
        resolution = Resolution(False, f"unexpected exception: {exc}")
        lease_lost = False
        traceback.print_exc(file=sys.stderr)

    if lease_lost:
        print(
            f"[cks-fork-agent] lost lease on crdt_fork task_id={task_id} while "
            "resolving (reclaimed by another worker) -- abandoning without "
            "completing/failing/dead-lettering it",
            file=sys.stderr,
        )
        return True

    if resolution.resolved:
        await complete_conflict_task(runtime, {"task_id": task_id})
        print(
            f"[cks-fork-agent] resolved crdt_fork task_id={task_id} "
            f"pointer_key={task['session_id']}",
            file=sys.stderr,
        )
        return True

    error = resolution.detail or "unknown error"
    next_retry_count = task["retry_count"] + 1
    if next_retry_count >= settings.max_retries:
        await dead_letter_conflict_task(runtime, {"task_id": task_id, "error": error})
        print(
            f"[cks-fork-agent] dead-lettered crdt_fork task_id={task_id} "
            f"after {next_retry_count} attempt(s): {error}",
            file=sys.stderr,
        )
    else:
        await fail_conflict_task(
            runtime,
            {"task_id": task_id, "retry_count": next_retry_count, "error": error},
        )
        print(
            f"[cks-fork-agent] retrying crdt_fork task_id={task_id} "
            f"(attempt {next_retry_count}/{settings.max_retries}): {error}",
            file=sys.stderr,
        )
    return True


async def run_once(
    runtime: Runtime, settings: ForkResolutionAgentSettings | None = None
) -> int:
    """
    Drain every currently-eligible ``crdt_fork`` task once (claiming
    one at a time until the queue reports empty), returning the total
    number of tasks processed. Used by the main loop's each iteration,
    and directly by tests / a one-shot mode that doesn't want to poll
    forever.
    """
    settings = settings or ForkResolutionAgentSettings.from_env()
    processed = 0
    while await _process_one(runtime, settings):
        processed += 1
    return processed


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def run_fork_agent(
    *,
    settings: ForkResolutionAgentSettings | None = None,
    max_iterations: int | None = None,
) -> None:
    """
    Construct this process' own ``Runtime`` (sharing storage with the
    main ``cks-mcp`` server via the same ``storage_path``) and loop:
    drain pending ``crdt_fork`` tasks, sleep ``poll_interval``, repeat.

    ``max_iterations``, when given, stops the loop after that many
    poll cycles instead of running forever -- used by tests and by a
    supervisor that wants to restart the process periodically rather
    than trust a single long-lived event loop.
    """
    settings = settings or ForkResolutionAgentSettings.from_env()

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
        f"[cks-fork-agent] started (storage_path={settings.storage_path!r}, "
        f"poll_interval={settings.poll_interval}s, max_retries={settings.max_retries}, "
        f"heartbeat_interval={settings.heartbeat_interval}s)",
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
        print("[cks-fork-agent] stopped", file=sys.stderr)


def main_sync() -> None:
    """Console-script entry point (see pyproject.toml's [project.scripts])."""
    asyncio.run(run_fork_agent())


if __name__ == "__main__":
    main_sync()