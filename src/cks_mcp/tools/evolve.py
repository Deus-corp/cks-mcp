"""
MCP Tool: evolve_knowledge.

Applies a sequence of structural operators to a knowledge structure.
"""

import json
from typing import Any, Dict, List

from cks.serialization import parse as cks_parse, SerializationError
from cks.evolution import compose, AddObject, AddRelation, RemoveObject, RemoveRelation
from cks.core import KnowledgeObject, CanonicalRelation, ObjectIdentity


def _parse_operations(ops_data: List[Dict[str, Any]]) -> List[Any]:
    """Parse a list of operation dictionaries into structural operators."""
    operators = []
    for i, op in enumerate(ops_data):
        op_type = op.get("type")
        if op_type is None:
            raise ValueError(f"Operation #{i}: missing 'type' field")
        if op_type == "add_object":
            identity_data = op.get("identity")
            if identity_data is None:
                raise ValueError(f"Operation #{i}: missing 'identity' field")
            identity = ObjectIdentity(**identity_data)
            obj = KnowledgeObject(identity=identity, structure=op.get("structure", {}))
            operators.append(AddObject(obj))
        elif op_type == "add_relation":
            identity_data = op.get("identity")
            if identity_data is None:
                raise ValueError(f"Operation #{i}: missing 'identity' field")
            identity = ObjectIdentity(**identity_data)
            participants = op.get("participants")
            if participants is None:
                raise ValueError(f"Operation #{i}: missing 'participants' field")
            relation_type = op.get("relation_type")
            if relation_type is None:
                raise ValueError(f"Operation #{i}: missing 'relation_type' field")
            relation = CanonicalRelation(
                identity=identity,
                participants=participants,
                relation_type=relation_type,
                structure=op.get("structure", {}),
            )
            operators.append(AddRelation(relation))
        elif op_type == "remove_object":
            object_id = op.get("object_id")
            if object_id is None:
                raise ValueError(f"Operation #{i}: missing 'object_id' field")
            operators.append(RemoveObject(object_id))
        elif op_type == "remove_relation":
            relation_id = op.get("relation_id")
            if relation_id is None:
                raise ValueError(f"Operation #{i}: missing 'relation_id' field")
            operators.append(RemoveRelation(relation_id))
        else:
            raise ValueError(f"Operation #{i}: unknown operation type '{op_type}'")
    return operators


def evolve_knowledge(json_data: str, operations: str) -> str:
    """
    Apply a sequence of structural operators to a knowledge structure.

    Args:
        json_data: A JSON string representing a Knowledge Structure.
        operations: A JSON string with an array of operation objects.

    Returns:
        A JSON string with the evolved Knowledge Structure.
    """
    try:
        data = json.loads(json_data) if isinstance(json_data, str) else json_data
        structure = cks_parse(data)
    except (json.JSONDecodeError, SerializationError) as exc:
        return json.dumps({"error": f"Failed to parse input: {exc}"})

    try:
        ops_data = json.loads(operations) if isinstance(operations, str) else operations
        operators = _parse_operations(ops_data)
    except (json.JSONDecodeError, ValueError) as exc:
        return json.dumps({"error": f"Failed to parse operations: {exc}"})

    try:
        evolved = compose(structure, operators)
    except Exception as exc:
        return json.dumps({"error": f"Evolution failed: {exc}"})

    # Serialize back to JSON
    from cks.serialization import serialize as cks_serialize
    return cks_serialize(evolved)