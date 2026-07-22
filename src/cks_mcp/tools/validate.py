import cks
from typing import Any
from cks.constraints.builtin import OPTIONAL_CONSTRAINTS_BY_NAME
from cks_runtime.runtime import Runtime
from cks_runtime.operations.operation_types import ValidateOperation

from cks_mcp import provenance
from cks_mcp.errors import invalid_json_error


def _serialize_diagnostic(diagnostic: Any) -> dict[str, Any]:
    return {
        "code": diagnostic.code,
        "severity": diagnostic.severity.value,
        "source": diagnostic.source.value,
        "message": diagnostic.message,
        "metadata": dict(diagnostic.metadata),
    }


EXTENSION_ALIASES: dict[str, str] = {
    "embedding_projection": "CKS-EXT-EMBEDDING-PROJECTION",
    "verification_record": "CKS-EXT-VERIFICATION-RECORD",
}

# Trust-bearing types are enforced unconditionally the moment they
# appear in a structure -- unlike EmbeddingProjection (harmless if
# unrecognized), an unchecked VerificationRecord looks exactly like a
# checked one to anyone reading the result. Both its shape (enforced
# here) and its provenance signature (_check_verification_record_provenance,
# already called unconditionally below) must not depend on the caller
# remembering to opt in.
_ALWAYS_ENFORCED_EXTENSIONS: frozenset[str] = frozenset({"verification_record"})

_OPTIONAL_BY_IDENTITY = {c.identity: c for c in OPTIONAL_CONSTRAINTS_BY_NAME.values()}


def resolve_extensions(names: list[str] | None) -> tuple[list[Any], list[str]]:
    if not names:
        return [], []

    resolved: list[Any] = []
    unknown: list[str] = []
    for name in names:
        identity = EXTENSION_ALIASES.get(name, name)
        constraint = _OPTIONAL_BY_IDENTITY.get(identity)
        if constraint is None:
            unknown.append(name)
        else:
            resolved.append(constraint)
    return resolved, unknown


def _has_type(structure: Any, object_type: str) -> bool:
    return any(obj.identity.type == object_type for obj in structure.objects)


def validate_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Validate either:
    - the current state of an existing session (if session_id is provided), or
    - a freshly parsed JSON structure (fallback compatibility path).
    """
    session_id = arguments.get("session_id")

    if session_id:
        session = runtime.get_session(session_id)
        if not session:
            return {"error": f"Session '{session_id}' not found."}
        structure = session.knowledge_structure
    else:
        try:
            structure = cks.parse(arguments["json_data"])
        except cks.SerializationError as exc:
            return invalid_json_error(str(exc))
        session = runtime.create_session(structure)

    requested = arguments.get("extensions") or []
    extensions, unknown = resolve_extensions(requested)
    if unknown:
        return {
            "error": "unknown_extension",
            "message": (
                f"Unknown validation extension(s): {', '.join(unknown)}. "
                f"Available extensions: {', '.join(sorted(EXTENSION_ALIASES)) or '(none)'}."
            ),
        }

    forced_names = {
        name for name in _ALWAYS_ENFORCED_EXTENSIONS
        if _has_type(structure, "VerificationRecord")
    }
    forced_constraints, _ = resolve_extensions(sorted(forced_names))
    for constraint in forced_constraints:
        if constraint not in extensions:
            extensions.append(constraint)

    tx = runtime.begin_transaction(session)
    tx.add_operation(
        ValidateOperation(
            "validate",
            knowledge_structure=structure,
            extra_constraints=extensions or None,
        )
    )
    version = runtime.commit_transaction(tx)

    diagnostics = [_serialize_diagnostic(d) for d in session.diagnostics]
    core_valid = not any(d["severity"] == "error" for d in diagnostics)

    diagnostics.extend(provenance.verify_structure_provenance(structure))

    valid = core_valid and not any(d["severity"] == "error" for d in diagnostics)

    return {
        "valid": valid,
        "version_id": version.version_id,
        "session_id": session.session_id,
        "extensions_applied": requested,
        "diagnostics": diagnostics,
    }