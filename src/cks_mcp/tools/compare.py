"""
MCP Tool: compare_structures.

Compares two knowledge structures for semantic equivalence.
"""

import json
from typing import Any, Dict

from cks.serialization import parse as cks_parse, SerializationError
from cks.core import KnowledgeStructure


def compare_structures(json_data_a: str, json_data_b: str) -> str:
    """
    Compare two knowledge structures for semantic equivalence.

    Args:
        json_data_a: A JSON string representing the first Knowledge Structure.
        json_data_b: A JSON string representing the second Knowledge Structure.

    Returns:
        A JSON string with equivalence result and details.
    """
    try:
        data_a = json.loads(json_data_a) if isinstance(json_data_a, str) else json_data_a
        structure_a = cks_parse(data_a)
    except (json.JSONDecodeError, SerializationError) as exc:
        return json.dumps({
            "error": f"Failed to parse first structure: {exc}",
            "equivalent": False,
        })

    try:
        data_b = json.loads(json_data_b) if isinstance(json_data_b, str) else json_data_b
        structure_b = cks_parse(data_b)
    except (json.JSONDecodeError, SerializationError) as exc:
        return json.dumps({
            "error": f"Failed to parse second structure: {exc}",
            "equivalent": False,
        })

    is_equivalent = structure_a.structurally_equivalent(structure_b)

    return json.dumps({
        "equivalent": is_equivalent,
        "objects_a": len(structure_a.objects),
        "objects_b": len(structure_b.objects),
        "relations_a": len(structure_a.relations()),
        "relations_b": len(structure_b.relations()),
    })