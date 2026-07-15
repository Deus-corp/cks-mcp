"""
MCP Tool: derive_knowledge.

Creates a new Knowledge Object derived from existing ones via a canonical derivation.
"""

import json
from typing import Any, Dict, List

from cks.serialization import parse as cks_parse, SerializationError
from cks.core import KnowledgeObject, ObjectIdentity


def derive_knowledge(json_data: str, premises: str, rule: str, conclusion_id: str, conclusion_type: str, conclusion_name: str) -> str:
    """
    Derive a new Knowledge Object from existing premises.

    Args:
        json_data: A JSON string representing a Knowledge Structure.
        premises: A JSON array of canonical identities used as premises.
        rule: The canonical inference rule identifier.
        conclusion_id: Canonical identity for the new Knowledge Object.
        conclusion_type: Canonical type for the new Knowledge Object.
        conclusion_name: Human-readable name for the new Knowledge Object.

    Returns:
        A JSON string with the updated Knowledge Structure containing the derivation.
    """
    try:
        data = json.loads(json_data) if isinstance(json_data, str) else json_data
        structure = cks_parse(data)
    except (json.JSONDecodeError, SerializationError) as exc:
        return json.dumps({"error": f"Failed to parse input: {exc}"})

    premise_ids = json.loads(premises) if isinstance(premises, str) else premises
    for pid in premise_ids:
        if structure.get(pid) is None:
            return json.dumps({"error": f"Premise '{pid}' not found in structure"})

    if structure.get(conclusion_id) is not None:
        return json.dumps({"error": f"Conclusion '{conclusion_id}' already exists in structure"})

    conclusion = KnowledgeObject(
        identity=ObjectIdentity(id=conclusion_id, type=conclusion_type, name=conclusion_name),
        structure={
            "derived_from": premise_ids,
            "rule": rule,
        },
    )

    # Build a new structure with the conclusion added
    objects = list(structure.objects)
    objects.append(conclusion)
    from cks.core import KnowledgeStructure
    new_structure = KnowledgeStructure(objects)

    from cks.serialization import serialize as cks_serialize
    return cks_serialize(new_structure)