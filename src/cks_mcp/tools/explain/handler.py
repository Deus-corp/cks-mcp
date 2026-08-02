from typing import Any

import cks
from cks_runtime.operations.operation_types import (
    ExplainInferenceOperation,
    ExplainOperation,
)
from cks_runtime.runtime import Runtime

from cks_mcp import provenance
from cks_mcp.errors import internal_error, invalid_json_error, unverified_provenance


def _build_explain_operation(structure: Any, object_id: str | None) -> Any:
    """
    Pick the read-only operation for this call: the general structure-wide
    explanation, or -- when ``object_id`` is given -- the "why is this
    object believed?" explanation (ADR-001), which walks its active
    InferenceStep chain(s) back to base facts via
    ``ExplainInferenceOperation``/``CoreBridge.explain_inference``.
    """
    if object_id:
        return ExplainInferenceOperation(
            "explain_inference",
            knowledge_structure=structure,
            object_id=object_id,
        )
    return ExplainOperation("explain", knowledge_structure=structure)


async def explain_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Explain either:
    - the current state of an existing session (if session_id is provided), or
    - a freshly parsed JSON structure (fallback compatibility path).

    In either case, if ``object_id`` is also given, explain *why* that one
    object is currently believed (``ExplainInferenceOperation``) instead of
    the general structure-wide explanation (``ExplainOperation``). An
    attached Core that doesn't implement the optional explain_inference
    capability, an unknown ``object_id``, or any other Core-side failure
    surfaces as a FAILED result, reported below as ``internal_error``
    rather than silently swallowed to ``{}`` -- unlike the general
    explanation, there is no meaningful empty default for "why".
    """
    object_id = arguments.get("object_id")
    session_id = arguments.get("session_id")
    if session_id:
        session = runtime.get_session(session_id)

        # Explain is read-only and must not create a new version in the
        # session's history. begin_transaction/commit_transaction always
        # persists a version regardless of whether anything changed (see
        # ExecutionPipeline.commit), so route through the non-committing
        # executor instead -- the same mechanism merge_branch already uses
        # for its conflict-detection dry-run.
        result = await runtime.executor.execute(
            _build_explain_operation(session.knowledge_structure, object_id),
            session,
        )
        if object_id and not result.succeeded:
            return internal_error(
                f"explain_inference failed for object_id={object_id!r}: {result.error!s}"
            )
        return {
            "session_id": session.session_id,
            "explanation": result.payload if result.succeeded else {},
        }

    try:
        structure = cks.parse(arguments["json_data"])
    except cks.SerializationError as exc:
        return invalid_json_error(str(exc))

    # Same provenance gate as serialize_knowledge -- see its
    # implementation for the full rationale (CHANGELOG 1.3.3).
    provenance_diagnostics = provenance.verify_structure_provenance(structure)
    if any(d["severity"] == "error" for d in provenance_diagnostics):
        return unverified_provenance("explain", provenance_diagnostics)

    session = await runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    tx.add_operation(_build_explain_operation(structure, object_id))
    await runtime.commit_transaction(tx)
    result = tx.results[0] if tx.results else None
    if object_id and result is not None and not getattr(result, "succeeded", True):
        return internal_error(
            f"explain_inference failed for object_id={object_id!r}: {result.error!s}"
        )
    return result.payload if result else {}