"""
explain_diff: human-readable explanation of changes between two versions.
"""

from typing import Any

from cks import AddObject, AddRelation, RemoveObject, RemoveRelation
from cks.evolution import RenameObject
from cks_runtime.runtime import Runtime
from cks_runtime.session.reconstruct import reconstruct_with_retry

from cks_mcp.diffing import field_level_diff
from cks_mcp.errors import missing_parameter, session_not_found


async def explain_diff(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Explain the differences between the current state and a target version."""
    session_id = arguments.get("session_id")
    if not session_id:
        return missing_parameter("session_id")

    session = runtime.get_session(session_id)
    if not session:
        return session_not_found(session_id)

    target_version_id = arguments.get("target_version_id")
    if not target_version_id:
        return missing_parameter("target_version_id")

    # Reconstruct the base version's state. A state-hash mismatch can
    # be a transient snapshot-consistency race (this handler's session
    # was read mid-write by a concurrent agent) rather than genuine
    # corruption, so reload the session once from storage and retry
    # before giving up -- same one-shot recovery as
    # OutboxEmbeddingWorker uses for the same error.
    try:
        base_structure = await reconstruct_with_retry(
            runtime.storage, session_id, session, target_version_id, runtime.core_bridge
        )
    except ValueError as exc:
        return {
            "error": f"Failed to reconstruct base version '{target_version_id}': {exc!s}"
        }

    current_structure = session.knowledge_structure

    # Compute diff
    try:
        patch = runtime.core_bridge.diff(
            source=base_structure,
            target=current_structure,
        )
    except Exception as e:
        return {"error": f"Failed to compute diff: {e!s}"}

    touched_object_ids: set[str] = set()
    touched_relation_ids: set[str] = set()
    renamed_objects: list[dict[str, Any]] = []

    for op in patch:
        if isinstance(op, AddObject):
            touched_object_ids.add(op.obj.identity.id)
        elif isinstance(op, RemoveObject):
            touched_object_ids.add(op.object_id)
        elif isinstance(op, AddRelation):
            touched_relation_ids.add(op.relation.identity.id)
        elif isinstance(op, RemoveRelation):
            touched_relation_ids.add(op.relation_id)
        elif isinstance(op, RenameObject):
            renamed_objects.append({"id": op.object_id, "new_name": op.new_name})

    def _classify(ids: set[str]) -> dict[str, list[dict[str, Any]]]:
        buckets: dict[str, list[dict[str, Any]]] = {
            "added": [],
            "deleted": [],
            "modified": [],
            "unchanged": [],
        }
        for identity_id in sorted(ids):
            diff_entry = field_level_diff(
                base_structure.get(identity_id), current_structure.get(identity_id)
            )
            action = diff_entry.get("action")
            if action in buckets:
                buckets[action].append({"id": identity_id, **diff_entry})
        return buckets

    object_buckets = _classify(touched_object_ids)
    relation_buckets = _classify(touched_relation_ids)

    added_objects = object_buckets["added"]
    removed_objects = object_buckets["deleted"]
    modified_objects = object_buckets["modified"]

    added_relations = relation_buckets["added"]
    removed_relations = relation_buckets["deleted"]
    modified_relations = relation_buckets["modified"]
    relinked_relations = relation_buckets["unchanged"]

    # InferenceStep objects (see cks-core ADR-001) carry the *why* behind
    # a conclusion -- premises, operator, confidence, justification --
    # not just the *what*. field_level_diff already puts the full
    # structure dict on each added_objects entry, so no extra lookup is
    # needed; this just reshapes it into a native reasoning summary
    # instead of leaving callers to notice type == "InferenceStep" and
    # dig through a generic "structure" blob themselves.
    added_inference_steps = []
    for obj in added_objects:
        if obj.get("type") != "InferenceStep":
            continue
        struct = obj.get("structure") or {}
        added_inference_steps.append({
            "id": obj["id"],
            "premises": struct.get("premises") or [],
            "conclusion": struct.get("conclusion"),
            "operator": struct.get("operator"),
            "confidence": struct.get("confidence"),
            "justification": struct.get("justification"),
        })

    # Natural language summary
    summary_parts = []
    if added_objects:
        summary_parts.append(
            f"Added {len(added_objects)} object(s): "
            + ", ".join(f"{o['name']} ({o['type']})" for o in added_objects)
        )
    if removed_objects:
        summary_parts.append(
            f"Removed {len(removed_objects)} object(s): "
            + ", ".join(f"{o['name']} ({o['type']})" for o in removed_objects)
        )
    if modified_objects:
        summary_parts.append(
            f"Modified {len(modified_objects)} object(s): "
            + ", ".join(f"{o['name']} ({o['type']})" for o in modified_objects)
        )
    if added_relations:
        summary_parts.append(f"Added {len(added_relations)} relation(s)")
    if removed_relations:
        summary_parts.append(f"Removed {len(removed_relations)} relation(s)")
    if modified_relations:
        summary_parts.append(f"Modified {len(modified_relations)} relation(s)")
    if relinked_relations:
        summary_parts.append(
            f"Re-linked {len(relinked_relations)} relation(s) with no actual "
            "change (one of their participants was replaced elsewhere in this diff)"
        )
    if renamed_objects:
        summary_parts.append(
            f"Renamed {len(renamed_objects)} object(s): "
            + ", ".join(f"{r['id']} → {r['new_name']}" for r in renamed_objects)
        )
    if added_inference_steps:
        def _describe_inference(step: dict) -> str:
            bits = [f"'{step['id']}'"]
            if step["conclusion"]:
                bits.append(f"concludes '{step['conclusion']}'")
            qualifier = []
            if step["operator"]:
                qualifier.append(step["operator"])
            if step["confidence"] is not None:
                qualifier.append(f"confidence {step['confidence']}")
            if qualifier:
                bits.append(f"({', '.join(qualifier)})")
            if step["premises"]:
                bits.append(f"from premises {step['premises']}")
            return " ".join(bits)

        summary_parts.append(
            f"Recorded {len(added_inference_steps)} inference(s): "
            + "; ".join(_describe_inference(s) for s in added_inference_steps)
        )

    if not summary_parts:
        summary_parts.append("No changes detected.")

    return {
        "session_id": session_id,
        "base_version_id": target_version_id,
        "summary": " ".join(summary_parts),
        "details": {
            "added_objects": added_objects,
            "removed_objects": removed_objects,
            "modified_objects": modified_objects,
            "added_relations": added_relations,
            "removed_relations": removed_relations,
            "modified_relations": modified_relations,
            "relinked_relations": relinked_relations,
            "renamed_objects": renamed_objects,
            "added_inference_steps": added_inference_steps,
        },
    }