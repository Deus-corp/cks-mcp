import cks
from typing import Any
from cks.constraints.builtin import OPTIONAL_CONSTRAINTS_BY_NAME
from cks_runtime.diagnostics.diagnostic import DiagnosticSeverity
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
    Проверяет наличие подписи provenance у всех VerificationRecord.
    Эта проверка выполняется БЕЗУСЛОВНО, так как объект типа VerificationRecord
    имеет смысл только при гарантированном происхождении.
    """
    subject_by_record: dict[str, str] = {}
    for relation in structure.relations():
        if relation.relation_type != "verified_by":
            continue
        if len(relation.participants) != 2:
            continue
        subject_id, record_id = relation.participants
        subject_by_record[record_id] = (
            subject_id if record_id not in subject_by_record else None
        )

    diagnostics: list[dict[str, Any]] = []
    for obj in structure.objects:
        if obj.identity.type != "VerificationRecord":
            continue

        subject_id = subject_by_record.get(obj.identity.id)
        if not subject_id:
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
                    f"VerificationRecord '{obj.identity.id}' does not carry a "
                    f"valid provenance signature. It must be produced by "
                    f"calling verify_source, not authored directly -- a "
                    f"well-formed but hand-written record is exactly what "
                    f"this check exists to catch."
                ),
                "metadata": {"location": obj.identity.id},
            })

    return diagnostics


def validate_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        structure = cks.parse(arguments["json_data"])
    except cks.SerializationError as exc:
        return invalid_json_error(str(exc))

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

    session = runtime.create_session(structure)
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

    # Проверка provenance теперь выполняется БЕЗУСЛОВНО
    diagnostics.extend(_check_verification_record_provenance(structure))

    valid = core_valid and not any(d["severity"] == "error" for d in diagnostics)

    return {
        "valid": valid,
        "version_id": version.version_id,
        "session_id": session.session_id,
        "extensions_applied": requested,
        "diagnostics": diagnostics,
    }