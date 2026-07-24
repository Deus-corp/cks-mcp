"""
merge_knowledge: three-way merge of Knowledge Structures.
merge_branch: session-aware three-way merge between two live sessions.
"""

from typing import Any
import cks
from cks_runtime.runtime import Runtime
from cks_runtime.core_api.merge_conflict import RuntimeMergeConflictError
from cks_runtime.execution.operation_executor import OperationStatus
from cks_runtime.operations.operation_types import MergeOperation
from cks_mcp.errors import missing_parameter, session_not_found
from cks_mcp import provenance


def _generate_diff(base_obj: Any, branch_obj: Any) -> dict[str, Any]:
    """
    Generate a human-readable diff between two KnowledgeObjects.
    """
    if base_obj is None and branch_obj is None:
        return {}
    if base_obj is None:
        return {
            "action": "added",
            "type": branch_obj.identity.type,
            "name": branch_obj.identity.name,
            "structure": dict(branch_obj.structure),
        }
    if branch_obj is None:
        return {"action": "deleted"}
    # Both exist — compute field-level changes
    changes = {}
    base_struct = dict(base_obj.structure)
    branch_struct = dict(branch_obj.structure)
    all_keys = set(base_struct) | set(branch_struct)
    for key in sorted(all_keys):
        old_val = base_struct.get(key)
        new_val = branch_struct.get(key)
        if old_val != new_val:
            changes[key] = {"from": old_val, "to": new_val}
    return {
        "action": "modified" if changes else "unchanged",
        "type": branch_obj.identity.type,
        "name": branch_obj.identity.name,
        "changes": changes,
    }


def merge_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Perform a three-way merge.

    Expects:
        json_data_base, json_data_branch_a, json_data_branch_b
    Returns the merged structure or a structured conflict report.
    """
    try:
        base = cks.parse(arguments["json_data_base"])
        branch_a = cks.parse(arguments["json_data_branch_a"])
        branch_b = cks.parse(arguments["json_data_branch_b"])
        merged = base.merge(branch_a, branch_b)
    except Exception as e:
        # Check if this is a merge conflict error by duck-typing
        if hasattr(e, 'conflicts'):
            return {
                "merged": False,
                "conflicts": [
                    {
                        "object_id": c.object_id,
                        "base": str(c.base) if c.base else None,
                        "branch_a": str(c.branch_a) if c.branch_a else None,
                        "branch_b": str(c.branch_b) if c.branch_b else None,
                    }
                    for c in e.conflicts
                ],
            }
        return {"error": str(e)}

    # Check provenance before returning merged result. Only
    # 'error'-severity diagnostics block -- see merge_branch for why
    # 'warning' (e.g. an as-yet-unlinked but genuinely-signed record)
    # must not.
    diags = provenance.verify_structure_provenance(merged)
    blocking = [d for d in diags if d["severity"] == "error"]
    if blocking:
        return {
            "merged": False,
            "error": "Provenance verification failed in merged result.",
            "details": blocking,
        }

    serialized = runtime.core_bridge.serialize(merged)
    return {
        "merged": True,
        "serialized": serialized,
    }


def _conflict_payload(error: RuntimeMergeConflictError) -> dict[str, Any]:
    return {
        "merged": False,
        "message": (
            "Merge conflict detected. Do not call merge_branch again "
            "unchanged -- inspect base_state/target_state/source_state "
            "for each conflict below, decide the correct combined "
            "content, and apply it to the target session yourself via "
            "evolve_knowledge. Once every conflict is resolved and any "
            "non-conflicting source changes you still want are carried "
            "over, close_session the source branch."
        ),
        "conflicts": [
            {
                "object_id": c.object_id,
                "target_diff": _generate_diff(c.base, c.branch_a),
                "source_diff": _generate_diff(c.base, c.branch_b),
            }
            for c in error.conflicts
        ],
    }


def merge_branch(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Session-aware three-way merge: merge a branch session's changes
    into a target session.

    Unlike merge_knowledge, callers never supply the merge base
    themselves -- it is resolved automatically from the branch's own
    recorded fork point (see create_branch), or from an explicit
    'base_version_id' pointing at a version in the *target* session's
    history.

    Expects:
        target_session_id (required) -- the session to merge into.
        source_session_id (required) -- the branch session being
            merged in.
        base_version_id (optional) -- override the merge base with a
            specific version id from the target session's history.
            Only needed when the source session wasn't created with a
            recorded 'parent_version_id' (i.e. create_branch was
            called without 'version_id').

    On success, returns the merged, serialized structure and commits
    it as a new version of the target session.

    On conflict, returns 'conflicts': a list of
    {object_id, base_state, target_state, source_state}. Do not retry
    merge_branch as-is -- resolve each conflict with evolve_knowledge
    on the target session instead (see the returned 'message').
    """
    target_session_id = arguments.get("target_session_id")
    source_session_id = arguments.get("source_session_id")

    if not target_session_id:
        return missing_parameter("target_session_id")
    if not source_session_id:
        return missing_parameter("source_session_id")

    target = runtime.get_session(target_session_id)
    if not target:
        return session_not_found(target_session_id)

    source = runtime.get_session(source_session_id)
    if not source:
        return session_not_found(source_session_id)

    base_version_id = arguments.get("base_version_id")

    def _operation() -> MergeOperation:
        return MergeOperation(
            "merge",
            source_session=source,
            base_version_id=base_version_id,
        )

    # Dry-run through the executor directly first (no transaction), so
    # a conflict is detected and reported without ever touching the
    # target session's committed state. See MergeOperation's docstring
    # in cks_runtime for why going straight through commit_transaction
    # would lose the structured conflict list.
    probe = runtime.executor.execute(_operation(), target)

    if probe.status == OperationStatus.FAILED:
        if isinstance(probe.error, RuntimeMergeConflictError):
            return _conflict_payload(probe.error)
        return {"error": f"merge_branch failed: {probe.error}"}

    # Check provenance on the prospective merged structure. `is not
    # None` rather than truthiness: KnowledgeStructure defines
    # __len__, so an empty-but-valid merge result would otherwise be
    # falsy and silently skip this check. Only 'error'-severity
    # diagnostics block -- a 'warning' (e.g. a genuinely-signed record
    # whose verified_by relation lives in a change not yet merged)
    # must not reject an otherwise-legitimate merge.
    if probe.payload is not None:
        diags = provenance.verify_structure_provenance(probe.payload)
        blocking = [d for d in diags if d["severity"] == "error"]
        if blocking:
            return {
                "error": "Cannot merge: VerificationRecord with invalid provenance found in merged result.",
                "details": blocking,
            }

    try:
        tx = runtime.begin_transaction(target)
        tx.add_operation(_operation())
        version = runtime.commit_transaction(tx)
    except Exception as e:
        return {"error": f"merge_branch failed: {str(e)}"}

    serialized = runtime.core_bridge.serialize(target.knowledge_structure)

    return {
        "merged": True,
        "serialized": serialized,
        "session_id": target.session_id,
        "version_id": version.version_id,
    }