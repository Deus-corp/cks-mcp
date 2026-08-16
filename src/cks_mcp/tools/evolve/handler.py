import asyncio
from typing import Any

import cks
from cks.evolution import RemoveObject, parse_operations
from cks_runtime.operations.operation_types import EvolveOperation
from cks_runtime.runtime import Runtime
from cks_runtime.session.session import RuntimeSession
from cks_runtime.storage.storage import ConcurrentModificationError

from cks_mcp import provenance
from cks_mcp.errors import invalid_json_error
from cks_mcp.tools.validate.handler import EXTENSION_ALIASES, resolve_extensions

#: number of extra attempts (beyond the first) evolve_knowledge makes
#: when committing races another writer -- see
#: ``_reload_session_from_storage``/the retry loop around
#: begin_transaction/commit_transaction below.
_MAX_COMMIT_RETRIES = 2

#: session_id -> the asyncio.Lock serializing evolve_knowledge calls
#: against that session within this process. Same pattern and same
#: reasoning as cks_runtime.gossip.adapter.GossipAdapter._lock_for:
#: TransactionManager.begin() raises "Session already has an active
#: transaction." the instant a second begin_transaction() call for the
#: same (in-memory, single-process) session lands while an earlier
#: call's transaction is still attached -- which happens routinely
#: once CKSAgentOrchestrator.run_concurrent starts two AgentSteps
#: (e.g. ResearcherStep and ReviewerStep) draining tasks that both
#: target the same sandbox session, since each task's evolve_knowledge
#: call spans several 'await' points (validation, provenance, commit)
#: with nothing else enforcing atomicity between them. Locking is
#: per-session_id, not global, so unrelated sessions still evolve
#: fully concurrently. This only ever serializes callers *within one
#: process* -- the retry loop below (ConcurrentModificationError) is
#: what handles a second process (e.g. the studio's own MCP server)
#: writing to the same session at the same time.
_session_locks: dict[str, asyncio.Lock] = {}


def _lock_for(session_id: str) -> asyncio.Lock:
    """Return the lock serializing evolve_knowledge calls for one
    session_id, creating it on first use. See `_session_locks` above.

    Lookup-and-insert here has no `await` between them, so this is
    race-free even without its own synchronization: the surrounding
    event loop is single-threaded, so nothing can interleave between
    the membership check and the assignment.
    """
    lock = _session_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _session_locks[session_id] = lock
    return lock


async def _reload_session_from_storage(
    runtime: Runtime, session: RuntimeSession
) -> RuntimeSession:
    """Refresh ``session`` in place from the persisted record.

    ``runtime.get_session``/the caller's ``session`` reference is the
    same in-memory object shared by every coroutine and (within one
    process) every pipeline step operating on this session_id --
    including ones running concurrently with this call (e.g. the
    studio evolving the session while a pipeline step is also
    evolving it, or two AgentStep drains sharing one sandbox session
    via ``CKSAgentOrchestrator.run_concurrent``). If storage has since
    advanced past what this in-memory object reflects (another
    process, or another commit that finished first), retrying a
    transaction against the stale copy would either immediately fail
    ``ConcurrentModificationError`` again or silently discard the
    other writer's committed change.

    Mutates ``session`` in place (rather than returning a new object)
    so every existing reference to it -- including the one the caller
    of ``evolve_knowledge`` still holds -- observes the refreshed
    state, matching ``SessionManager.restore``'s "same identity,
    fresher content" contract used at startup.
    """
    fresh = await runtime.storage.load_session(session.session_id)
    if fresh is not None:
        session.knowledge_structure = fresh.knowledge_structure
        session.version_history = fresh.version_history
        session.metadata = fresh.metadata
        session.closed = fresh.closed
    return session


async def evolve_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    session_id = arguments.get("session_id")
    if session_id:
        # Serialize concurrent evolve_knowledge calls against this
        # session within this process (see `_lock_for`'s docstring) --
        # acquired around the whole read-modify-commit sequence below,
        # not just begin/commit_transaction, since two concurrent
        # callers must not interleave *at all* on one session: one
        # must fully finish (or give up) before the next reads it.
        async with _lock_for(session_id):
            return await _evolve_knowledge_locked(runtime, arguments, session_id)
    return await _evolve_knowledge_locked(runtime, arguments, session_id)


async def _evolve_knowledge_locked(
    runtime: Runtime, arguments: dict[str, Any], session_id: str | None
) -> dict[str, Any]:
    session_existed = bool(session_id)
    if session_id:
        session = runtime.get_session(session_id)
        if not session:
            return {"error": f"Session '{session_id}' not found."}
        structure = session.knowledge_structure
    else:
        try:
            structure = cks.parse(arguments["json_data"])
        except cks.SerializationError as exc:
            return invalid_json_error(str(exc))
        # Same reasoning as validate_knowledge: don't persist a
        # session for content that might still be rejected by the
        # provenance check below. Use a throwaway, unregistered
        # session for the dry-run.
        session = RuntimeSession(knowledge_structure=structure)

    try:
        operations = parse_operations(arguments.get("operations", []))
    except ValueError as exc:
        return {
            "error": "invalid_operations",
            "message": f"Could not parse 'operations': {exc}",
        }

    if not operations:
        return {
            "error": "no_operations",
            "message": "No evolution operations were provided.",
        }

    # Opt-in validation extensions (see validate_knowledge): without
    # this, the commit-time cks.validate() call below only ever checks
    # BUILTIN_CONSTRAINTS, so an evolution that sets InferenceStep
    # fields directly (e.g. 'update_object'/'resolve_inference_conflict'
    # writing 'superseded_by') could commit a broken supersession chain
    # or an out-of-range confidence value with no way for the caller to
    # ask for those checks at commit time -- previously the only way to
    # catch that was a separate, after-the-fact validate_knowledge call
    # against the already-committed version.
    requested_extensions = arguments.get("extensions") or []
    extensions, unknown = resolve_extensions(requested_extensions)
    if unknown:
        return {
            "error": "unknown_extension",
            "message": (
                f"Unknown validation extension(s): {', '.join(unknown)}. "
                f"Available extensions: {', '.join(sorted(EXTENSION_ALIASES)) or '(none)'}."
            ),
        }

    # Dry-run to check provenance before committing. Unmetered: this is
    # a probe, not a committed operation -- the real execution (and the
    # one that should show up in get_metrics) happens below via
    # commit_transaction. Without record_metrics=False here, every
    # successful evolve_knowledge call would be counted twice.
    op = EvolveOperation("evolve", knowledge_structure=structure, evolution=operations)
    result = await runtime.executor.execute(op, session, record_metrics=False)
    if result.status.value == "failed":
        return {"error": f"Evolution failed: {result.error}"}
    prospective_structure = result.payload

    # Verify provenance of the prospective new state. Only an
    # 'error'-severity diagnostic (forged/tampered signature, or an
    # ambiguous verified_by target) blocks the commit -- a 'warning'
    # (e.g. CKS-MCP-UNLINKED-VERIFICATION-RECORD, a genuinely-signed
    # record whose verified_by relation hasn't been added in *this*
    # call) must not, or a legitimate record added and linked across
    # two separate evolve_knowledge calls could never succeed.
    diags = provenance.verify_structure_provenance(prospective_structure)
    blocking = [d for d in diags if d["severity"] == "error"]
    if blocking:
        return {
            "error": "validation_failed",
            "message": "Cannot commit evolution: VerificationRecord has invalid or missing provenance signature.",
            "details": blocking,
        }

    # Validate the evolved structure before committing
    try:
        validation = cks.validate(prospective_structure, extra_constraints=extensions or None)
    except Exception as e:
        return {
            "error": "validation_error",
            "message": f"Could not validate evolved structure: {e}",
        }
    if not validation.is_valid:
        return {
            "error": "validation_failed",
            "message": "Evolution would produce an invalid structure.",
            "diagnostics": [
                {
                    "code": d.identity,
                    "severity": d.severity.value,
                    "message": d.message,
                    "location": d.location,
                }
                for d in validation.diagnostics
            ],
        }

    # validation.is_valid only means no ERROR-severity diagnostic was
    # raised -- a WARNING/INFORMATION from a built-in constraint or an
    # opted-in extension (e.g. CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT,
    # CKS-EXT-STALE-PREMISE) can still be present here and was
    # previously discarded once the commit succeeded, silently hiding
    # e.g. a newly-created belief conflict from the caller. Surfaced
    # below on every successful commit, regardless of whether
    # 'extensions' was used.
    non_blocking_diagnostics = [
        {
            "code": d.identity,
            "severity": d.severity.value,
            "message": d.message,
            "location": d.location,
        }
        for d in validation.diagnostics
    ]

    if not session_existed:
        session = await runtime.create_session(structure)

    # Reload right before opening the transaction: 'session' may have
    # been read (via runtime.get_session above) some time before this
    # point -- the provenance/validation work above is not free, and a
    # concurrent writer (studio, another pipeline step, another
    # process) may have committed in the meantime. Reloading here
    # doesn't fully close that race on its own (see the retry loop
    # below for that), but it does mean the common case -- nothing
    # else touched this session between read and write -- never pays
    # a ConcurrentModificationError + retry round trip it didn't need.
    if session_existed:
        await _reload_session_from_storage(runtime, session)

    version = None
    for attempt in range(_MAX_COMMIT_RETRIES + 1):
        tx = runtime.begin_transaction(session)
        tx.add_operation(op)
        try:
            version = await runtime.commit_transaction(tx)
            break
        except ConcurrentModificationError:
            # commit_transaction failed *after* attach_transaction, so
            # the session is left with an active_transaction that will
            # never be committed/rolled back unless we clear it -- the
            # next begin_transaction call would otherwise immediately
            # raise "Session already has an active transaction."
            # instead of the retry we actually want.
            #
            # Deliberately runtime.transactions.abort(tx) here, NOT
            # runtime.abort_transaction(tx): the latter goes through
            # ExecutionPipeline.abort(), which does an unconditional
            # (no expected_version_id) storage.save_session() -- since
            # the transaction already mutated session.knowledge_structure
            # in place (_execute_operations runs before the failed
            # persist), that blind save would clobber the very write
            # that just won the race with our own stale, never-persisted
            # state. TransactionManager.abort() only flips the
            # transaction's status and detaches it from the session --
            # no storage I/O -- which is what we want here since
            # _reload_session_from_storage below is about to replace
            # session.knowledge_structure with the real persisted state
            # anyway.
            runtime.transactions.abort(tx)
            if attempt >= _MAX_COMMIT_RETRIES:
                return {
                    "error": "concurrent_modification",
                    "message": (
                        f"Session '{session.session_id}' was modified "
                        "concurrently and evolve_knowledge could not "
                        f"commit after {_MAX_COMMIT_RETRIES + 1} attempts. "
                        "Reload the session and retry."
                    ),
                }
            await _reload_session_from_storage(runtime, session)
            # The operation's own EvolveOperation was built against a
            # structure snapshot; the dry-run/provenance/validation
            # checks above already ran against that snapshot, not the
            # freshly-reloaded one. Re-run them against the reloaded
            # structure before retrying the commit, so a retry can't
            # commit an evolution that validation never actually
            # cleared for the state it's now being applied on top of.
            structure = session.knowledge_structure
            op = EvolveOperation("evolve", knowledge_structure=structure, evolution=operations)
            retry_result = await runtime.executor.execute(op, session, record_metrics=False)
            if retry_result.status.value == "failed":
                return {"error": f"Evolution failed: {retry_result.error}"}
            prospective_structure = retry_result.payload
            retry_diags = provenance.verify_structure_provenance(prospective_structure)
            retry_blocking = [d for d in retry_diags if d["severity"] == "error"]
            if retry_blocking:
                return {
                    "error": "validation_failed",
                    "message": "Cannot commit evolution: VerificationRecord has invalid or missing provenance signature.",
                    "details": retry_blocking,
                }
            try:
                validation = cks.validate(prospective_structure, extra_constraints=extensions or None)
            except Exception as e:
                return {
                    "error": "validation_error",
                    "message": f"Could not validate evolved structure: {e}",
                }
            if not validation.is_valid:
                return {
                    "error": "validation_failed",
                    "message": "Evolution would produce an invalid structure.",
                    "diagnostics": [
                        {
                            "code": d.identity,
                            "severity": d.severity.value,
                            "message": d.message,
                            "location": d.location,
                        }
                        for d in validation.diagnostics
                    ],
                }
            non_blocking_diagnostics = [
                {
                    "code": d.identity,
                    "severity": d.severity.value,
                    "message": d.message,
                    "location": d.location,
                }
                for d in validation.diagnostics
            ]

    assert version is not None  # loop only exits via break or an early return above

    # Detect cascade-deleted relations caused by RemoveObject operations
    cascade_removed: list[str] = []
    for op in operations:
        if isinstance(op, RemoveObject):
            removed_id = op.object_id
            for rel in structure.relations():
                if removed_id in rel.participants and rel.identity.id not in {
                    r.identity.id for r in session.knowledge_structure.relations()
                }:
                    cascade_removed.append(rel.identity.id)

    serialized = runtime.core_bridge.serialize(session.knowledge_structure)
    response = {
        "evolved": True,
        "serialized": serialized,
        "operations_applied": len(operations),
        "version_id": version.version_id,
        "session_id": session.session_id,
    }
    if cascade_removed:
        response["cascade_removed_relations"] = cascade_removed
    if requested_extensions:
        response["extensions_applied"] = requested_extensions
    if non_blocking_diagnostics:
        response["diagnostics"] = non_blocking_diagnostics
    return response