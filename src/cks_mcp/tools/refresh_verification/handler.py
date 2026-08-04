"""
refresh_verification: resolve a ``provenance_conflict`` task (ADR-010's
``ProvenanceStalenessSweeper``, in cks-runtime) by re-checking the
original source and producing a fresh, signed ``VerificationRecord``.

Where does this sit relative to the other conflict-resolution tools
=====================================================================
``arbitrate_inference_conflict`` and ``resolve_gossip_conflict`` are
both three-path tools (interactive / auto_resolve via an LLM / bypass)
because resolving *their* conflicts is a judgment call -- picking a
winning InferenceStep, or choosing a side of a structural merge --
that genuinely benefits from either a human-in-the-loop client or an
LLM's reasoning.

Refreshing a stale VerificationRecord is not that kind of conflict.
Per ADR-010 and ``ProvenanceStalenessSweeper``'s own docstring, the
resolution is always the same mechanical action: perform the HTTP
check again and sign the result -- exactly what ``verify_source``
already does, unconditionally, with no room for an LLM (or a human) to
"decide" anything differently. So this tool has exactly one path:
call ``verify_source`` again with the same ``subject_id``/``source_url``
the stale record was originally checked against, and (optionally)
commit the new record in place of nothing -- the old, stale record is
never deleted; VerificationRecords are immutable once signed, and the
new one simply becomes the current provenance for ``subject_id``.

``auto_resolve`` is accepted in the schema purely so this tool's call
shape matches ``arbitrate_inference_conflict``'s/
``resolve_gossip_conflict``'s from the Critic Agent's point of view --
see ``ProvenanceStalenessSweeper``'s own docstring, which already
documents the expected call as
``refresh_verification(auto_resolve=True, commit=True)``. It is a
pure no-op here: this tool never makes an LLM call, with or without
it.
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.tools.evolve.handler import evolve_knowledge
from cks_mcp.tools.verify_source.handler import verify_source


def _operations_from_verify_source_objects(
    objects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Translate verify_source's ``{"objects": [record, relation]}`` result
    into evolve_knowledge ``operations`` -- ``add_object`` for the new
    VerificationRecord, ``add_relation`` for its ``verified_by`` link to
    the subject. Mirrors the shape cks.evolution.parse_operations expects
    (see that module's ``add_object``/``add_relation`` branches).
    """
    operations: list[dict[str, Any]] = []
    for obj in objects:
        identity = obj["identity"]
        if identity.get("type") == "Relation":
            structure = obj["structure"]
            operations.append(
                {
                    "type": "add_relation",
                    "identity": identity,
                    "participants": structure["participants"],
                    "relation_type": structure["relation_type"],
                }
            )
        else:
            operations.append(
                {
                    "type": "add_object",
                    "identity": identity,
                    "structure": obj["structure"],
                }
            )
    return operations


async def refresh_verification(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    session_id = arguments["session_id"]
    stale_record_id = arguments["record_id"]
    subject_id = arguments["subject_id"]
    source_url = arguments["source_url"]

    # The one and only resolution path: re-run the exact same real HTTP
    # check + signature verify_source already performs. No LLM, no
    # human decision -- see module docstring.
    verify_result = await verify_source(
        runtime, {"url": source_url, "subject_id": subject_id}
    )

    if verify_result.get("error"):
        # e.g. "unsafe_url" -- the source itself is no longer safe to
        # check (SSRF-guard rejection, DNS failure, ...). Surface this
        # as-is rather than wrapping it, so a caller/Critic Agent already
        # handling verify_source's error shapes doesn't need a second one.
        return {
            "stale_record_id": stale_record_id,
            "subject_id": subject_id,
            "source_url": source_url,
            **verify_result,
        }

    new_objects = verify_result["objects"]
    new_record = new_objects[0]

    response: dict[str, Any] = {
        "session_id": session_id,
        "stale_record_id": stale_record_id,
        "subject_id": subject_id,
        "source_url": source_url,
        "new_record": new_record,
        "objects": new_objects,
    }

    if arguments.get("commit"):
        evolve_result = await evolve_knowledge(
            runtime,
            {
                "session_id": session_id,
                "operations": _operations_from_verify_source_objects(new_objects),
                "extensions": ["verification_record"],
            },
        )
        response["commit_result"] = evolve_result

    return response