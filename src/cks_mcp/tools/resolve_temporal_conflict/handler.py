"""
resolve_temporal_conflict: resolve a ``temporal_conflict`` task (ADR-011's
``TemporalStalenessSweeper``, in cks-runtime) -- a KnowledgeObject whose
``valid_until`` has already passed, per cks-core's opt-in
``TemporalValidityConstraint`` (ADR-003).

Where does this sit relative to the other conflict-resolution tools
=====================================================================
``arbitrate_inference_conflict`` and ``resolve_gossip_conflict`` are
three-path tools (interactive / auto_resolve via an LLM / bypass)
because resolving *their* conflicts is a genuine judgment call.
``refresh_verification`` is the opposite extreme: exactly one
mechanical action (re-run ``verify_source``), no decision at all.

This tool sits in between. Unlike a stale VerificationRecord, an
expired fact does not have one canonical remedy -- a human or Critic
Agent has to decide what an expired ``valid_until`` *means* for this
particular object: is the fact still true and just needs a new
deadline ("bump"), is it genuinely over and should be retired
("archive"), or is the expiry a false positive that can be
acknowledged and left alone ("ignore")? What this tool does *not*
do is pick that decision for the caller -- unlike
``arbitrate_inference_conflict``/``resolve_gossip_conflict`` there is
no ``auto_resolve`` (LLM) path here, because unlike ranking
InferenceSteps by entrenchment or picking a side of a structural
merge, there is no principled default for "what should this fact's
new expiry be" or "should this fact be archived" -- that is a
domain judgment only the caller (human-in-the-loop, or a Critic Agent
that already knows the answer) can supply via the required ``action``
argument. Once ``action`` is chosen, applying it is purely mechanical:
exactly one ``update_object``/``remove_object`` operation via
``evolve_knowledge``, mirroring how ``refresh_verification`` always
routes its own single mechanical action through the same tool.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.errors import invalid_parameter, missing_parameter, session_not_found
from cks_mcp.tools.evolve.handler import evolve_knowledge

_VALID_ACTIONS = ("bump", "archive", "ignore")


def _find_object(session: Any, object_id: str) -> dict[str, Any] | None:
    """Look up an object's current structure/type by id in a session's
    live KnowledgeStructure. Returns ``None`` if not found (e.g. it was
    already removed by an earlier resolution of the same conflict)."""
    structure = session.knowledge_structure
    if structure is None:
        return None
    for obj in structure.objects:
        if obj.identity.id == object_id:
            return {"type": obj.identity.type, "structure": dict(obj.structure)}
    return None


def _parse_valid_until(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


async def resolve_temporal_conflict(
    runtime: Runtime, arguments: dict[str, Any]
) -> dict[str, Any]:
    session_id = arguments.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return missing_parameter("session_id")

    object_id = arguments.get("object_id")
    if not isinstance(object_id, str) or not object_id:
        return missing_parameter("object_id")

    action = arguments.get("action", "ignore")
    if action not in _VALID_ACTIONS:
        return invalid_parameter("action", action, list(_VALID_ACTIONS))

    session = runtime.get_session(session_id)
    if session is None:
        return session_not_found(session_id)

    current = _find_object(session, object_id)
    if current is None:
        return {
            "error": "object_not_found",
            "message": (
                f"Object '{object_id}' was not found in session "
                f"'{session_id}' -- it may have already been removed or "
                "renamed by an earlier resolution of this conflict."
            ),
        }

    response: dict[str, Any] = {
        "session_id": session_id,
        "object_id": object_id,
        "action": action,
    }

    operations: list[dict[str, Any]] = []

    if action == "bump":
        extend_by_days = arguments.get("extend_by_days")
        if extend_by_days is None:
            return missing_parameter("extend_by_days")
        try:
            extend_by_days = float(extend_by_days)
        except (TypeError, ValueError):
            return {
                "error": "invalid_parameter",
                "message": (
                    f"'extend_by_days' must be a number, got {extend_by_days!r}."
                ),
            }
        if extend_by_days <= 0:
            return {
                "error": "invalid_parameter",
                "message": "'extend_by_days' must be a positive number.",
            }

        current_valid_until = _parse_valid_until(
            current["structure"].get("valid_until")
        )
        # Extend from whichever is later: the object's current
        # valid_until, or now. An object whose valid_until is far in
        # the past (the common case -- that is exactly why it was
        # escalated) should not have its new deadline anchored to that
        # stale timestamp; extending "now" forward is what a caller
        # asking to "give this fact N more days" actually means.
        now = datetime.now(UTC)
        anchor = max(current_valid_until, now) if current_valid_until else now
        new_valid_until = anchor + timedelta(days=extend_by_days)

        response["previous_valid_until"] = current["structure"].get("valid_until")
        response["new_valid_until"] = new_valid_until.isoformat()

        operations.append(
            {
                "type": "update_object",
                "object_id": object_id,
                "structure_patch": {"valid_until": new_valid_until.isoformat()},
                "mode": "merge",
            }
        )

    elif action == "archive":
        # Mark the object as archived and drop 'valid_until' so it no
        # longer trips TemporalValidityConstraint / gets re-escalated
        # by a future sweep -- an archived fact is deliberately retired,
        # not "still expired". The object itself is kept (not
        # RemoveObject) so any relations referencing it, and the record
        # of what it once asserted, survive.
        response["archived_at"] = datetime.now(UTC).isoformat()
        operations.append(
            {
                "type": "update_object",
                "object_id": object_id,
                "structure_patch": {
                    "archived": True,
                    "archived_at": response["archived_at"],
                    "valid_until": None,
                },
                "mode": "merge",
            }
        )

    else:  # action == "ignore"
        # A pure acknowledgment: the human/Critic Agent looked at the
        # expiry and decided nothing should change. There is no
        # structural operation to apply -- an 'ignore' resolution never
        # calls evolve_knowledge, 'commit' included, since there is
        # nothing to commit.
        response["acknowledged"] = True
        return response

    response["operations"] = operations

    if arguments.get("commit"):
        evolve_result = await evolve_knowledge(
            runtime,
            {
                "session_id": session_id,
                "operations": operations,
                "extensions": ["temporal_validity"],
            },
        )
        response["commit_result"] = evolve_result

    return response