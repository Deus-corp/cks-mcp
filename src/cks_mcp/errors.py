"""
Structured error responses for LLM-friendly diagnostics.
"""

def invalid_json_error() -> dict:
    return {
        "error": "invalid_json",
        "message": "The provided json_data is not a valid JSON string. Please check the syntax and try again."
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