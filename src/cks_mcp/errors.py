"""
Structured error responses for LLM-friendly diagnostics.
"""


def invalid_json_error(details: str | None = None) -> dict:
    message = "The provided json_data could not be parsed into a Knowledge Structure."
    if details:
        message += f" Details: {details}"
    else:
        message += " Please check the syntax and try again."
    return {
        "error": "invalid_json",
        "message": message,
    }


def validation_failed(details: str) -> dict:
    return {
        "error": "validation_failed",
        "message": f"The knowledge structure is invalid. Details: {details}",
    }


def unknown_extension(extensions: list[str]) -> dict:
    return {
        "error": "unknown_extension",
        "message": f"Unknown validation extension(s): {', '.join(extensions)}. Available: embedding_projection, verification_record.",
    }


def invalid_parameter(name: str, value: object, allowed: list[str]) -> dict:
    """
    A parameter was given a value outside its enum of allowed values.

    Mirrors ``unknown_extension``'s shape for the same reason: MCP
    servers don't enforce JSON Schema server-side, so a handler that
    accepts an enum-like string (e.g. visualize_graph's ``mode``) needs
    its own defensive check and an LLM-friendly message listing what
    *was* accepted, not just that the call failed.
    """
    return {
        "error": "invalid_parameter",
        "message": f"Invalid value {value!r} for parameter '{name}'. "
        f"Allowed: {', '.join(allowed)}.",
    }


def missing_parameter(name: str) -> dict:
    return {
        "error": "missing_parameter",
        "message": f"Missing required parameter: '{name}'.",
    }


def session_not_found(session_id: str) -> dict:
    return {
        "error": "session_not_found",
        "message": f"Session '{session_id}' not found.",
    }


def graph_not_found(name: str) -> dict:
    return {
        "error": "graph_not_found",
        "message": f"No graph is registered under name '{name}'.",
    }


def empty_query() -> dict:
    return {
        "error": "empty_query",
        "message": "Query must not be empty.",
    }


def internal_error(details: str) -> dict:
    return {
        "error": "internal_error",
        "message": f"Internal error: {details}",
    }


def unverified_provenance(action: str, diagnostics: list[dict]) -> dict:
    """
    A structure carrying a VerificationRecord with an invalid or missing
    provenance signature was about to be committed as a persisted
    session/version by `action` (e.g. "serialize", "explain"). Used by
    every json_data entry point that calls runtime.create_session --
    see cks_mcp.provenance.verify_structure_provenance and CHANGELOG
    1.3.3 for why this must block *before* create_session, not after.
    """
    return {
        "error": "unverified_provenance",
        "message": (
            f"Cannot {action}: structure contains a VerificationRecord "
            "with an invalid or missing provenance signature. It must be "
            "produced by calling verify_source, not authored directly."
        ),
        "details": diagnostics,
    }