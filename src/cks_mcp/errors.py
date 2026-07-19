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
        "message": f"The knowledge structure is invalid. Details: {details}"
    }

def unknown_extension(extensions: list[str]) -> dict:
    return {
        "error": "unknown_extension",
        "message": f"Unknown validation extension(s): {', '.join(extensions)}. Available: embedding_projection, verification_record."
    }