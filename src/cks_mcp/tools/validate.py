"""
MCP Tool: validate_knowledge.

Validates a canonical knowledge structure and returns diagnostics.
"""

import json
from typing import Any, Dict

from cks.serialization import parse as cks_parse, SerializationError
from cks.validator import validate as cks_validate
from cks.diagnostics import DiagnosticSeverity


def validate_knowledge(json_data: str) -> str:
    """
    Validate a knowledge structure in canonical JSON format.

    Args:
        json_data: A JSON string representing a Knowledge Structure.

    Returns:
        A JSON string with validation result and diagnostics.
    """
    try:
        data = json.loads(json_data) if isinstance(json_data, str) else json_data
        structure = cks_parse(data)
    except (json.JSONDecodeError, SerializationError) as exc:
        return json.dumps({
            "valid": False,
            "error": f"Failed to parse input: {exc}",
            "diagnostics": [],
        })

    result = cks_validate(structure)

    diagnostics = []
    for diag in result.diagnostics:
        diagnostics.append({
            "identity": diag.identity,
            "severity": diag.severity.value,
            "message": diag.message,
            "location": diag.location,
        })

    return json.dumps({
        "valid": result.is_valid,
        "error_count": result.error_count,
        "warning_count": result.warning_count,
        "diagnostics": diagnostics,
    })