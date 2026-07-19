import cks
from typing import Any
from cks.constraints.builtin import OPTIONAL_CONSTRAINTS
from cks_runtime.diagnostics.diagnostic import DiagnosticSeverity
from cks_runtime.runtime import Runtime
from cks_runtime.operations.operation_types import ValidateOperation
from cks.constraints.builtin import OPTIONAL_CONSTRAINTS_BY_NAME


def _serialize_diagnostic(diagnostic: Any) -> dict[str, Any]:
    return {
        "code": diagnostic.code,
        "severity": diagnostic.severity.value,
        "source": diagnostic.source.value,
        "message": diagnostic.message,
        "metadata": dict(diagnostic.metadata),
    }


# ----------------------------------------------------------------------
# Optional validation extensions
# ----------------------------------------------------------------------
#
# OPTIONAL_CONSTRAINTS ships opt-in rules (e.g. anti-hallucination
# citation checking via EmbeddingProjectionIntegrityConstraint) that
# are deliberately not part of cks-core's default constraint set.
# MCP tool arguments arrive as plain JSON, so callers select
# extensions by short, stable name rather than passing Constraint
# objects (which they cannot construct) or cks-core's internal
# "CKS-EXT-..." identity strings (an implementation detail).

EXTENSION_ALIASES: dict[str, str] = {
    "embedding_projection": "CKS-EXT-EMBEDDING-PROJECTION",
    "verification_record": "CKS-EXT-VERIFICATION-RECORD",
}

_OPTIONAL_BY_IDENTITY = {c.identity: c for c in OPTIONAL_CONSTRAINTS_BY_NAME.values()}


def resolve_extensions(names: list[str] | None) -> tuple[list[Any], list[str]]:
    """
    Resolve requested extension names to Constraint instances.

    Returns (resolved_constraints, unknown_names). Never raises: an
    unknown name is reported back to the caller instead, since a
    thrown exception here would otherwise surface to the LLM as an
    opaque JSON-RPC -32000 error with no actionable information.
    """
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


def validate_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    structure = cks.parse(arguments["json_data"])

    extensions, unknown = resolve_extensions(arguments.get("extensions"))
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

    diagnostics = list(session.diagnostics)
    valid = not any(d.severity is DiagnosticSeverity.ERROR for d in diagnostics)

    return {
        "valid": valid,
        "version_id": version.version_id,
        "session_id": session.session_id,
        "extensions_applied": [n for n in (arguments.get("extensions") or [])],
        "diagnostics": [_serialize_diagnostic(d) for d in diagnostics],
    }