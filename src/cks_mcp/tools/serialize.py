from typing import Any

import cks
from cks_runtime.operations.operation_types import SerializeOperation
from cks_runtime.runtime import Runtime

from cks_mcp import provenance
from cks_mcp.errors import invalid_json_error, unverified_provenance


async def serialize_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> Any:
    """
    Serialize either:
    - the current state of an existing session (if session_id is provided), or
    - a freshly parsed JSON structure (fallback compatibility path).
    """
    session_id = arguments.get("session_id")
    if session_id:
        session = runtime.get_session(session_id)
        if not session:
            return {"error": f"Session '{session_id}' not found."}

        try:
            return {
                "session_id": session.session_id,
                "serialized": runtime.core_bridge.serialize(
                    session.knowledge_structure
                ),
            }
        except Exception as exc:
            return {
                "error": "serialization_failed",
                "message": f"Could not serialize session '{session_id}': {exc}",
            }

    try:
        structure = cks.parse(arguments["json_data"])
    except cks.SerializationError as exc:
        return invalid_json_error(str(exc))

    # Same provenance gate validate_knowledge/evolve_knowledge/
    # merge_knowledge enforce before ever calling create_session (which
    # persists immediately, via storage.save_session). Without this,
    # a caller could bypass validate_knowledge entirely and commit a
    # forged VerificationRecord as a real, readable session just by
    # calling serialize_knowledge with json_data directly -- see
    # CHANGELOG 1.3.3, which closed this exact bypass for
    # validate_knowledge itself; the json_data fallback path here and
    # in explain_knowledge was never updated to match.
    provenance_diagnostics = provenance.verify_structure_provenance(structure)
    if any(d["severity"] == "error" for d in provenance_diagnostics):
        return unverified_provenance("serialize", provenance_diagnostics)

    session = await runtime.create_session(structure)
    tx = runtime.begin_transaction(session)
    tx.add_operation(SerializeOperation("serialize", knowledge_structure=structure))
    await runtime.commit_transaction(tx)
    result = tx.results[0] if tx.results else None
    return result.payload if result else ""