"""
compare_versions: structural diff between session versions.
"""

from __future__ import annotations

from typing import Any

from cks_runtime.runtime import Runtime
from cks_runtime.operations.operation_types import DiffOperation
from cks_runtime.execution.operation_executor import OperationStatus


def _build_summary(payload: list[Any]) -> dict[str, int]:
    """
    Build a lightweight semantic summary from a list of StructuralOperators.
    """
    summary = {
        "added_objects": 0,
        "removed_objects": 0,
        "added_relations": 0,
        "removed_relations": 0,
    }

    for op in payload:
        if hasattr(op, '_obj'):
            summary["added_objects"] += 1
        elif hasattr(op, '_relation_id'):
            summary["removed_relations"] += 1
        elif hasattr(op, '_object_id'):
            summary["removed_objects"] += 1
        elif hasattr(op, '_relation'):
            summary["added_relations"] += 1

    return summary


def compare_versions(
    runtime: Runtime,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """
    Compare the current session state with a historical version.

    Direction is always:

        base_version (target_version_id)
                →
        current session state

    Therefore:

        add_*    = exists only in current state

        remove_* = exists only in base version
    """

    session_id = arguments.get("session_id")
    target_version_id = arguments.get("target_version_id")

    if not session_id:
        return {"error": "Missing required parameter: session_id"}

    if not target_version_id:
        return {"error": "Missing required parameter: target_version_id"}

    session = runtime.get_session(session_id)

    if session is None:
        return {"error": f"Session '{session_id}' not found."}

    tx = runtime.begin_transaction(session)

    tx.add_operation(
        DiffOperation(
            "diff",
            target_version_id=target_version_id,
        )
    )

    runtime.commit_transaction(tx)

    result = tx.results[0] if tx.results else None

    if result is None:
        return {"error": "Diff operation produced no result."}

    if result.status == OperationStatus.FAILED:
        return {
            "error": f"Failed to compute diff: {result.error}"
        }

    payload = result.payload
    current_version_id = None
    if session.version_history:
        current_version_id = session.version_history[-1].version_id

    return {
        "session_id": session.session_id,

        # Explicit semantics for LLMs
        "base_version_id": target_version_id,
        "current_version_id": current_version_id,
        "direction": "base_to_current",

        # Human/LLM friendly summary
        "summary": _build_summary(payload),

        # Raw runtime payload (source of truth)
        "operations": payload,
    }