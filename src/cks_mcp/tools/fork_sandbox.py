"""
fork_sandbox: create an ephemeral 'what-if' branch, optionally apply a
hypothesis to it immediately, and report how it diverges from its
fork point -- all without ever touching the parent session.
"""

from __future__ import annotations

from typing import Any

import cks
from cks.evolution import parse_operations
from cks_runtime.operations.operation_types import EvolveOperation
from cks_runtime.runtime import Runtime

from cks_mcp import provenance
from cks_mcp.errors import missing_parameter, session_not_found
from cks_mcp.tools.compare import _build_summary, _serialize_operators


async def fork_sandbox(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    parent_session_id = arguments.get("session_id")
    if not parent_session_id:
        return missing_parameter("session_id")

    parent = runtime.get_session(parent_session_id)
    if not parent:
        return session_not_found(parent_session_id)

    version_id = arguments.get("version_id")
    try:
        branch = await runtime.create_branch(parent, version_id=version_id)
    except ValueError as exc:
        return {"error": "branch_failed", "message": str(exc)}

    fork_structure = branch.knowledge_structure
    hypothesis = arguments.get("hypothesis")
    operations_applied = 0

    raw_operations = arguments.get("operations") or []
    if raw_operations:
        try:
            operations = parse_operations(raw_operations)
        except ValueError as exc:
            await runtime.close_session(branch.session_id)
            return {
                "error": "invalid_operations",
                "message": f"Could not parse 'operations': {exc}",
            }

        op = EvolveOperation(
            "evolve", knowledge_structure=fork_structure, evolution=operations
        )
        result = await runtime.executor.execute(op, branch, record_metrics=False)
        if result.status.value == "failed":
            await runtime.close_session(branch.session_id)
            return {
                "error": "evolution_failed",
                "message": f"Hypothesis could not be applied: {result.error}",
            }
        prospective_structure = result.payload

        diags = provenance.verify_structure_provenance(prospective_structure)
        blocking = [d for d in diags if d["severity"] == "error"]
        if blocking:
            await runtime.close_session(branch.session_id)
            return {
                "error": "validation_failed",
                "message": (
                    "Cannot commit hypothesis: VerificationRecord has "
                    "invalid or missing provenance signature."
                ),
                "details": blocking,
            }

        validation = cks.validate(prospective_structure)
        if not validation.is_valid:
            await runtime.close_session(branch.session_id)
            return {
                "error": "validation_failed",
                "message": "Applying this hypothesis would produce an invalid structure.",
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

        tx = runtime.begin_transaction(branch)
        tx.add_operation(op)
        await runtime.commit_transaction(tx)
        operations_applied = len(operations)

    diff_ops = runtime.core_bridge.diff(
        source=fork_structure,
        target=branch.knowledge_structure,
    )
    serialized_diff = _serialize_operators(diff_ops)

    response: dict[str, Any] = {
        "sandbox_session_id": branch.session_id,
        "parent_session_id": parent.session_id,
        "fork_version_id": branch.parent_version_id,
        "operations_applied": operations_applied,
        "diff_from_fork_point": {
            "summary": _build_summary(serialized_diff),
            "operations": serialized_diff,
        },
        "message": (
            f"Sandbox session '{branch.session_id}' is an isolated fork "
            f"of '{parent.session_id}'; nothing here affects the parent. "
            f"Keep exploring it with evolve_knowledge, promote it with "
            f"merge_branch once satisfied, or discard it with "
            f"close_session -- there is no obligation to merge."
        ),
    }
    if hypothesis:
        response["hypothesis"] = hypothesis
    return response