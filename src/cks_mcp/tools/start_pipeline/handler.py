"""
start_pipeline: enqueue 'pipeline_research_request' tasks for a
session's objects, the same task_type/queue ResearcherStep
(cks_mcp.pipeline.researcher_step) drains -- and the same generic
enqueue_task storage method request_enrichment already uses, so this
handler stays a thin producer with no orchestrator-specific storage
path of its own.

This is deliberately *only* an enqueue. Actually running the pipeline
against those tasks is the job of a standalone 'cks-pipeline-agent'
process (cks_mcp.pipeline_agent, wrapping CKSAgentOrchestrator) already
polling the same outbox -- see that module's docstring. A thin client
like cks-studio calling this tool gets an immediate response with what
was enqueued; it does not get "the pipeline is done" back, because
nothing here waits for a single step to run, let alone the whole
pipeline.
"""

from __future__ import annotations

import json
from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.errors import internal_error, invalid_parameter, missing_parameter
from cks_mcp.orchestrator import pipeline_run_hash
from cks_mcp.pipeline.researcher_step import TASK_TYPE as _RESEARCH_TASK_TYPE
from cks_mcp.tools.fork_sandbox.handler import fork_sandbox

_VALID_MODES = ("sequential", "concurrent")
_DEFAULT_SCHEMA_VERSION = "v1"


def _all_object_ids(session: Any) -> list[str]:
    """Every object id currently in ``session``'s live knowledge
    structure, in structure order. Mirrors the
    ``structure.objects`` / ``identity.id`` walk
    ``CKSAgentOrchestrator._check_idempotency_cache`` already uses to
    read a session's objects, rather than introducing a second way to
    enumerate them."""
    structure = getattr(session, "knowledge_structure", None)
    if structure is None:
        return []
    object_ids: list[str] = []
    for obj in structure.objects:
        identity = getattr(obj, "identity", None)
        obj_id = getattr(identity, "id", None) if identity is not None else None
        if obj_id:
            object_ids.append(str(obj_id))
    return object_ids


async def start_pipeline(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    session_id = arguments.get("session_id")
    if not session_id:
        return missing_parameter("session_id")

    mode = arguments.get("mode") or "sequential"
    if mode not in _VALID_MODES:
        return invalid_parameter("mode", mode, list(_VALID_MODES))

    # require_open_session (registry.py's middleware wrapper for this
    # tool) has already confirmed session_id exists and is open by the
    # time the handler itself runs; runtime.get_session is re-fetched
    # here (rather than trusted from middleware) only because the
    # handler needs the live session object itself, not just the fact
    # that it exists.
    session = runtime.get_session(session_id)
    if session is None:
        return internal_error(f"session '{session_id}' not found")

    if not runtime.storage.supports_outbox:
        return {
            "status": "unsupported",
            "supported": False,
            "message": (
                "This storage backend does not support the persistent outbox "
                "(e.g. the default InMemoryStorage). A pipeline run requires a "
                "shared SQLite or Postgres backend, same as request_enrichment."
            ),
        }

    object_ids = arguments.get("object_ids") or None
    if object_ids:
        # Explicit ids are taken as-is: this tool enqueues exactly the
        # objects named, not their graph neighbourhood. A wider
        # "research this object's neighbours too" policy belongs to
        # ResearcherStep itself (it already decides what a finding
        # links to) or a future dedicated parameter -- silently
        # expanding the caller's own explicit list here would make
        # 'enqueued_objects' lie about what was actually requested.
        object_ids = [str(oid) for oid in object_ids]
    else:
        object_ids = _all_object_ids(session)
        if not object_ids:
            return {
                "run_id": None,
                "mode": mode,
                "enqueued_objects": [],
                "status": "no_objects",
                "supported": True,
                "message": f"Session '{session_id}' has no objects to run the pipeline against.",
            }

    schema_version = arguments.get("schema_version") or _DEFAULT_SCHEMA_VERSION
    parent_session_id = arguments.get("parent_session_id") or None

    # Phase 1 safety (requirement 5): when the caller opts into sandbox
    # isolation, fork parent_session_id up front and enqueue against
    # the resulting branch, exactly the isolation
    # CKSAgentOrchestrator._enter_sandbox already gives a caller of
    # run_sequential/run_concurrent -- so a pipeline started from this
    # tool never writes to parent_session_id directly, only to the
    # sandbox, pending a separate merge_branch. Token budget and the
    # idempotency cache are per-orchestrator-run concerns (they live on
    # CKSAgentOrchestrator/PipelineContext, entered on each
    # run_sequential/run_concurrent call) rather than per-enqueue ones,
    # so nothing here duplicates them; run_id below reuses the exact
    # same pipeline_run_hash so a caller can still recognize an
    # equivalent run.
    target_session_id = session_id
    sandbox_session_id: str | None = None
    if parent_session_id:
        fork_result = await fork_sandbox(runtime, {"session_id": parent_session_id})
        sandbox_session_id = fork_result.get("sandbox_session_id")
        if sandbox_session_id is None:
            return internal_error(
                f"fork_sandbox failed for parent_session_id={parent_session_id!r}: "
                f"{fork_result.get('message') or fork_result.get('error')}"
            )
        target_session_id = sandbox_session_id

    run_id = pipeline_run_hash(parent_session_id or session_id, object_ids, schema_version)

    for object_id in object_ids:
        await runtime.storage.enqueue_task(
            task_type=_RESEARCH_TASK_TYPE,
            session_id=target_session_id,
            payload=json.dumps({"object_id": object_id, "run_id": run_id}),
        )

    response: dict[str, Any] = {
        "run_id": run_id,
        "mode": mode,
        "enqueued_objects": object_ids,
        "status": "started",
        "supported": True,
        "session_id": target_session_id,
    }
    if sandbox_session_id is not None:
        response["sandbox_session_id"] = sandbox_session_id
        response["parent_session_id"] = parent_session_id
    return response
