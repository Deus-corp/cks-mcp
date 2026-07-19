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


def _check_verification_record_provenance(structure: Any) -> list[dict[str, Any]]:
    """
    Checks that every VerificationRecord has a valid provenance signature.
    Also reports ambiguous verified_by mappings explicitly.
    """
    record_to_subject: dict[str, str] = {}
    ambiguous_records: set[str] = set()

    for relation in structure.relations():
        if relation.relation_type != "verified_by":
            continue
        if len(relation.participants) != 2:
            continue

        subject_id, record_id = relation.participants
        existing = record_to_subject.get(record_id)
        if existing is None:
            record_to_subject[record_id] = subject_id
        elif existing != subject_id:
            ambiguous_records.add(record_id)

    diagnostics: list[dict[str, Any]] = []

    for record_id in ambiguous_records:
        diagnostics.append({
            "code": "CKS-MCP-AMBIGUOUS-VERIFICATION-REFERENCE",
            "severity": "error",
            "source": "mcp",
            "message": (
                f"VerificationRecord '{record_id}' is referenced by multiple subjects "
                f"through 'verified_by'. This relationship is ambiguous and must be resolved."
            ),
            "metadata": {"location": record_id},
        })

    for obj in structure.objects:
        if obj.identity.type != "VerificationRecord":
            continue

        if obj.identity.id in ambiguous_records:
            continue

        subject_id = record_to_subject.get(obj.identity.id)
        if not subject_id:
            diagnostics.append({
                "code": "CKS-MCP-UNLINKED-VERIFICATION-RECORD",
                "severity": "warning",
                "source": "mcp",
                "message": (
                    f"VerificationRecord '{obj.identity.id}' has no verified_by relation. "
                    f"It will not be treated as a trusted provenance record."
                ),
                "metadata": {"location": obj.identity.id},
            })
            continue

        ok = provenance.verify(
            record_id=obj.identity.id,
            subject_id=subject_id,
            checked_at=obj.structure.get("checked_at", ""),
            checked_via=obj.structure.get("checked_via", ""),
            http_status=obj.structure.get("http_status"),
            signature=obj.structure.get(provenance.SIGNATURE_KEY),
        )
        if not ok:
            diagnostics.append({
                "code": "CKS-MCP-UNVERIFIED-PROVENANCE",
                "severity": "error",
                "source": "mcp",
                "message": (
                    f"VerificationRecord '{obj.identity.id}' does not carry a valid provenance signature. "
                    f"It must be produced by calling verify_source, not authored directly."
                ),
                "metadata": {"location": obj.identity.id},
            })

    return diagnostics


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

    diagnostics.extend(_check_verification_record_provenance(structure))

    valid = core_valid and not any(d["severity"] == "error" for d in diagnostics)

    return {
        "valid": valid,
        "version_id": version.version_id,
        "session_id": session.session_id,
        "extensions_applied": requested,
        "diagnostics": diagnostics,
    }