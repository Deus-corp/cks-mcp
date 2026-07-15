"""Tests for query_relations tool."""
import json
from cks_mcp.tools.query import query_relations


def test_query_relations():
    """Query an entity that has relations."""
    data = json.dumps({
        "objects": [
            {"identity": {"id": "obj-1", "type": "Definition", "name": "Alice"}, "structure": {}},
            {"identity": {"id": "obj-2", "type": "Definition", "name": "Bob"}, "structure": {}},
            {
                "identity": {"id": "rel-1", "type": "Relation", "name": "knows"},
                "structure": {"participants": ["obj-1", "obj-2"], "relation_type": "knows"},
            },
        ]
    })
    result = json.loads(query_relations(data, "obj-1"))
    assert len(result["relations"]) == 1
    assert result["relations"][0]["relation_type"] == "knows"


def test_query_no_relations():
    """Query an entity with no relations."""
    data = json.dumps({
        "objects": [
            {"identity": {"id": "obj-1", "type": "Definition", "name": "Alice"}, "structure": {}},
        ]
    })
    result = json.loads(query_relations(data, "obj-1"))
    assert len(result["relations"]) == 0