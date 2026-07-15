"""
MCP Tool: query_relations.

Returns all canonical relations for a given entity.
"""

import json
from typing import Any, Dict, List

from cks.serialization import parse as cks_parse, SerializationError


def query_relations(json_data: str, entity_id: str) -> str:
    """
    Query all relations for a given entity in a knowledge structure.

    Args:
        json_data: A JSON string representing a Knowledge Structure.
        entity_id: The canonical identity of the entity to query.

    Returns:
        A JSON string with the list of relations involving the entity.
    """
    try:
        data = json.loads(json_data) if isinstance(json_data, str) else json_data
        structure = cks_parse(data)
    except (json.JSONDecodeError, SerializationError) as exc:
        return json.dumps({
            "error": f"Failed to parse input: {exc}",
            "relations": [],
        })

    relations: List[Dict[str, Any]] = []
    for rel in structure.relations():
        if entity_id in rel.participants:
            relations.append({
                "relation_id": rel.identity.id,
                "relation_type": rel.relation_type,
                "participants": list(rel.participants),
            })

    return json.dumps({
        "entity_id": entity_id,
        "relations": relations,
    })