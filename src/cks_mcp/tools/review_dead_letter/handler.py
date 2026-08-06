"""
review_dead_letter: look up a single dead-lettered conflict task and
propose a ready-to-apply resolution for it, so a human/operator does
not need to know each conflict-resolution tool's own parameter shape
to act on it.

This tool is purely mechanical -- it never calls an LLM and never
decides *how* to resolve a conflict. It only translates a DEAD task's
``task_type``/``payload`` into a call ``approve_resolution`` can apply
verbatim (or with manual edits, e.g. a different ``winner_id``):

    gossip_conflict        -> resolve_gossip_conflict
    inference_conflict     -> arbitrate_inference_conflict
    provenance_conflict    -> refresh_verification
    temporal_conflict      -> resolve_temporal_conflict
    contradiction_detected -> resolve_contradiction

The mapping mirrors ``cks_mcp.critic_agent``'s own ``_RESOLVERS`` /
per-type resolver functions -- this tool proposes exactly the same
call an unattended Critic Agent would have made automatically, just
surfaced for a human to review, edit, and approve instead of applying
it unattended. Diagnostic codes/defaults below (e.g.
``CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT``, the 30-day temporal bump)
are intentionally kept in sync with critic_agent.py's own constants
rather than importing its private (underscore-prefixed) names, so this
read-only review path has no runtime dependency on that module's
internals.
"""

from __future__ import annotations

import json
from typing import Any

from cks_runtime.runtime import Runtime

# Kept in sync with cks_mcp.critic_agent's own private constants of the
# same names -- see this module's docstring for why they're duplicated
# rather than imported.
_ARBITRABLE_DIAGNOSTIC_CODE = "CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT"
_STALE_PREMISE_CODE = "CKS-EXT-STALE-PREMISE"
_TEMPORAL_BUMP_EXTEND_DAYS = 30


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


def _propose_gossip_conflict(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    source_session_id = payload.get("source_session_id")
    if not source_session_id:
        return {
            "error": "cannot_propose",
            "message": "payload has no 'source_session_id' -- cannot propose a merge.",
        }
    return {
        "tool": "resolve_gossip_conflict",
        "arguments": {
            "target_session_id": session_id,
            "source_session_id": source_session_id,
        },
    }


def _propose_inference_conflict(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    diagnostics = payload.get("diagnostics") or []
    conclusion_ids = _extract_locations(diagnostics, _ARBITRABLE_DIAGNOSTIC_CODE)
    stale_premise_ids = _extract_locations(diagnostics, _STALE_PREMISE_CODE)

    if conclusion_ids:
        return {
            "tool": "arbitrate_inference_conflict",
            "arguments": {
                "session_id": session_id,
                "conclusion_ids": conclusion_ids,
                "auto_resolve": True,
                "commit": True,
            },
        }
    if stale_premise_ids:
        return {
            "tool": "arbitrate_inference_conflict",
            "arguments": {
                "session_id": session_id,
                "stale_premise_ids": stale_premise_ids,
                "commit": True,
            },
        }
    return {
        "error": "cannot_propose",
        "message": (
            "payload has no CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT or "
            "CKS-EXT-STALE-PREMISE diagnostics -- nothing to arbitrate."
        ),
    }


def _propose_provenance_conflict(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    record_id = payload.get("record_id")
    subject_id = payload.get("subject_id")
    source_url = payload.get("source_url")

    if not record_id or not subject_id:
        return {
            "error": "cannot_propose",
            "message": (
                "payload is missing 'record_id' and/or 'subject_id' -- cannot "
                "refresh a verification without knowing which record/subject "
                "it belongs to."
            ),
        }
    if not source_url:
        return {
            "error": "cannot_propose",
            "message": (
                f"payload has no 'source_url' for subject_id={subject_id!r} -- "
                "the subject carries no 'url' field, so there is nothing to "
                "re-check automatically."
            ),
        }
    return {
        "tool": "refresh_verification",
        "arguments": {
            "session_id": session_id,
            "record_id": record_id,
            "subject_id": subject_id,
            "source_url": source_url,
            "auto_resolve": True,
            "commit": True,
        },
    }


def _propose_temporal_conflict(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    object_id = payload.get("object_id")
    if not object_id:
        return {
            "error": "cannot_propose",
            "message": (
                "payload has no 'object_id' -- cannot bump a valid_until "
                "without knowing which object it belongs to."
            ),
        }
    return {
        "tool": "resolve_temporal_conflict",
        "arguments": {
            "session_id": session_id,
            "object_id": object_id,
            "action": "bump",
            "extend_by_days": _TEMPORAL_BUMP_EXTEND_DAYS,
            "commit": True,
        },
    }


def _propose_contradiction_detected(session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    location = payload.get("location")
    if not location:
        return {
            "error": "cannot_propose",
            "message": (
                "payload has no 'location' -- cannot resolve a contradiction "
                "without knowing which one it refers to."
            ),
        }
    return {
        "tool": "resolve_contradiction",
        "arguments": {
            "session_id": session_id,
            "contradiction_ids": [location],
            "commit": True,
        },
    }


_PROPOSERS = {
    "gossip_conflict": _propose_gossip_conflict,
    "inference_conflict": _propose_inference_conflict,
    "provenance_conflict": _propose_provenance_conflict,
    "temporal_conflict": _propose_temporal_conflict,
    "contradiction_detected": _propose_contradiction_detected,
}


def propose_resolution(task_type: str, session_id: str, payload: Any) -> dict[str, Any]:
    """Build a ``proposed_resolution`` for a dead-lettered task, or an
    ``error``/``message`` dict if the task_type is unrecognized or the
    payload doesn't carry enough information to propose one."""
    if not isinstance(payload, dict):
        return {
            "error": "cannot_propose",
            "message": f"payload was not a JSON object: {payload!r}",
        }
    proposer = _PROPOSERS.get(task_type)
    if proposer is None:
        return {
            "error": "unknown_task_type",
            "message": f"No known resolution tool for task_type={task_type!r}.",
        }
    return proposer(session_id, payload)


async def review_dead_letter(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    task_id = arguments["task_id"]

    if not runtime.storage.supports_outbox:
        return {
            "error": "not_supported",
            "message": (
                "This storage backend does not support the persistent outbox "
                "(e.g. the default InMemoryStorage) -- there is no dead-letter "
                "queue to review."
            ),
        }

    tasks = await runtime.storage.list_dead_letter_tasks()
    task = next((t for t in tasks if t.task_id == task_id), None)

    if task is None:
        return {
            "error": "task_not_dead_lettered",
            "message": (
                f"Task {task_id!r} was not found among DEAD-lettered tasks -- "
                "it may not exist, or it may not currently be in the DEAD "
                "state (only dead_letter_conflict_task puts a task there; "
                "see list_dead_lettered_conflicts for the current set)."
            ),
        }

    try:
        payload = json.loads(task.payload)
    except (json.JSONDecodeError, TypeError):
        payload = task.payload

    proposed_resolution = propose_resolution(task.task_type, task.session_id, payload)

    return {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "session_id": task.session_id,
        "payload": payload,
        "retry_count": task.retry_count,
        "last_error": task.last_error,
        "proposed_resolution": proposed_resolution,
    }
