"""
detect_contradictions: surface logical contradictions in a Knowledge
Structure, using the contradiction extension constraints in cks-core.

Read-only, like explain_knowledge/serialize_knowledge/query_subgraph:
runs a dry-run ValidateOperation scoped to the contradiction
constraints, and reshapes its diagnostics into a compact
'contradictions' list.
"""

from __future__ import annotations

from typing import Any

import cks
from cks_runtime.operations.operation_types import ValidateOperation
from cks_runtime.runtime import Runtime
from cks_runtime.session.session import RuntimeSession

from cks_mcp.errors import invalid_json_error, missing_parameter, session_not_found
from cks_mcp.tools.validate.handler import _serialize_diagnostic, resolve_extensions

# All contradiction/conflict constraints considered by this tool.
# CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT (see cks-core ADR-001) is
# WARNING severity, not ERROR like the other two -- it's a resolvable
# belief conflict between agreeing InferenceSteps, not a hard,
# jointly-nonsensical contradiction -- but it belongs in this tool's
# output for the same reason the other two do: it's a pattern that's
# only visible when reading multiple objects together.
_CONTRADICTION_IDENTITIES = {
    "CKS-EXT-MUTUAL-EXCLUSION",
    "CKS-EXT-FUNCTIONAL-RELATION",
    "CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT",
}


async def detect_contradictions(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Detect contradictions in either:
    - the current state of an existing session (if session_id is provided), or
    - a freshly parsed JSON structure (fallback compatibility path).
    """
    session_id = arguments.get("session_id")
    if session_id:
        session = runtime.get_session(session_id)
        if not session:
            return session_not_found(session_id)
        structure = session.knowledge_structure
    else:
        if "json_data" not in arguments:
            return missing_parameter("json_data")
        try:
            structure = cks.parse(arguments["json_data"])
        except cks.SerializationError as exc:
            return invalid_json_error(str(exc))
        session = RuntimeSession(knowledge_structure=structure)

    # Opt into all three contradiction/conflict extensions
    constraints, unknown = resolve_extensions(
        ["mutual_exclusion", "functional_relation", "inference_confidence_conflict"]
    )
    # unknown should always be empty here, but handle gracefully
    if unknown:
        return {
            "error": "unknown_extension",
            "message": f"Unknown contradiction extension(s): {', '.join(unknown)}",
        }

    op = ValidateOperation(
        "validate",
        knowledge_structure=structure,
        extra_constraints=constraints,
    )
    # record_metrics=False: this is a read-only inspection, same as
    # query_subgraph/explain_knowledge.
    result = await runtime.executor.execute(op, session, record_metrics=False)

    contradictions = [
        _serialize_diagnostic(d)
        for d in (result.diagnostics or [])
        if d.code in _CONTRADICTION_IDENTITIES
    ]

    response: dict[str, Any] = {
        "contradiction_count": len(contradictions),
        "contradictions": contradictions,
    }
    if session_id:
        response["session_id"] = session.session_id
    return response