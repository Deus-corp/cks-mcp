import cks
from typing import Any
from cks.constraints.builtin import OPTIONAL_CONSTRAINTS_BY_NAME
from cks_runtime.runtime import Runtime
from cks_runtime.operations.operation_types import ValidateOperation
from cks_runtime.session.session import RuntimeSession

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
    session_existed = bool(session_id)

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
        # Do NOT call runtime.create_session() yet -- it persists
        # immediately (storage.save_session), which would make a
        # forged VerificationRecord live and readable via
        # serialize_knowledge/explain_knowledge/query_subgraph/MCP
        # Resources on the returned session_id even though the
        # provenance gate below correctly refuses to commit a
        # *version* for it. Use a throwaway, unregistered session for
        # the dry-run instead; only create_session (which persists)
        # once the structure has actually been accepted.
        session = RuntimeSession(knowledge_structure=structure)

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

    # Provenance signatures are an MCP-level concern cks-core has no
    # way to check itself (it never sees the signing key), so they are
    # verified separately from -- and BEFORE any decision to commit
    # alongside -- core-level validation. A structure carrying a
    # forged VerificationRecord must never become a persisted version,
    # "invalid" or not: once committed, a version is exactly what a
    # downstream reader (serialize_knowledge, explain_knowledge,
    # query_subgraph, an MCP Resource, another agent's evolve_knowledge/
    # merge_branch call) will treat as trustworthy, regardless of what
    # this call's own 'valid' field said. This mirrors the dry-run-
    # before-commit gate already used by evolve_knowledge and
    # merge_branch/merge_knowledge for the same reason.
    provenance_diagnostics = provenance.verify_structure_provenance(structure)
    provenance_ok = not any(d["severity"] == "error" for d in provenance_diagnostics)

    op = ValidateOperation(
        "validate",
        knowledge_structure=structure,
        extra_constraints=extensions or None,
    )

    if provenance_ok:
        if not session_existed:
            session = runtime.create_session(structure)
        tx = runtime.begin_transaction(session)
        tx.add_operation(op)
        version = runtime.commit_transaction(tx)
        core_diagnostics = [_serialize_diagnostic(d) for d in session.diagnostics]
        version_id = version.version_id
    else:
        # Dry-run only, straight through the executor (bypassing the
        # transaction/commit pipeline entirely): still surface
        # core-level diagnostics for a complete report, but never let
        # this structure reach a persisted version. session.diagnostics
        # is only ever populated by the commit pipeline (see
        # ExecutionPipeline._handle_result), so diagnostics come from
        # the ExecutionResult directly here instead.
        result = runtime.executor.execute(op, session)
        core_diagnostics = [_serialize_diagnostic(d) for d in (result.diagnostics or [])]
        version_id = None

    core_valid = not any(d["severity"] == "error" for d in core_diagnostics)
    diagnostics = core_diagnostics + provenance_diagnostics
    valid = core_valid and provenance_ok

    response: dict[str, Any] = {
        "valid": valid,
        "extensions_applied": requested,
        "diagnostics": diagnostics,
    }
    # Only reference a session that was actually persisted. A fresh
    # json_data structure rejected for provenance was never registered
    # via create_session, so its session_id doesn't point at anything
    # durable (same reasoning as omitting version_id below).
    if session_existed or provenance_ok:
        response["session_id"] = session.session_id
    if version_id is not None:
        response["version_id"] = version_id
    return response