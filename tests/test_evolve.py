"""Tests for evolve_knowledge tool."""
import json
from cks_mcp.tools.evolve import evolve_knowledge


def test_evolve_add_object():
    """Add a new object via evolution."""
    data = json.dumps({
        "objects": [
            {"identity": {"id": "obj-1", "type": "Definition", "name": "Test"}, "structure": {}},
        ]
    })
    ops = json.dumps([
        {
            "type": "add_object",
            "identity": {"id": "obj-2", "type": "Definition", "name": "New"},
            "structure": {},
        }
    ])
    result = evolve_knowledge(data, ops)
    assert "obj-2" in result
    assert "obj-1" in result


def test_evolve_remove_object():
    """Remove an object via evolution."""
    data = json.dumps({
        "objects": [
            {"identity": {"id": "obj-1", "type": "Definition", "name": "Test"}, "structure": {}},
            {"identity": {"id": "obj-2", "type": "Definition", "name": "Other"}, "structure": {}},
        ]
    })
    ops = json.dumps([
        {"type": "remove_object", "object_id": "obj-2"}
    ])
    result = evolve_knowledge(data, ops)
    assert "obj-1" in result
    assert "obj-2" not in result


def test_evolve_invalid_operations():
    """Invalid operations should return an error."""
    data = json.dumps({
        "objects": [
            {"identity": {"id": "obj-1", "type": "Definition", "name": "Test"}, "structure": {}},
        ]
    })
    result = json.loads(evolve_knowledge(data, "invalid"))
    assert "error" in result