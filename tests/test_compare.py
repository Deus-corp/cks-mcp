"""Tests for compare_structures tool."""
import json
from cks_mcp.tools.compare import compare_structures


def test_compare_equivalent():
    """Two identical structures should be equivalent."""
    data_a = json.dumps({
        "objects": [
            {"identity": {"id": "obj-1", "type": "Definition", "name": "Test"}, "structure": {}},
        ]
    })
    data_b = json.dumps({
        "objects": [
            {"identity": {"id": "obj-1", "type": "Definition", "name": "Test"}, "structure": {}},
        ]
    })
    result = json.loads(compare_structures(data_a, data_b))
    assert result["equivalent"] is True


def test_compare_different():
    """Structures with different objects should not be equivalent."""
    data_a = json.dumps({
        "objects": [
            {"identity": {"id": "obj-1", "type": "Definition", "name": "Test"}, "structure": {}},
        ]
    })
    data_b = json.dumps({
        "objects": [
            {"identity": {"id": "obj-2", "type": "Definition", "name": "Other"}, "structure": {}},
        ]
    })
    result = json.loads(compare_structures(data_a, data_b))
    assert result["equivalent"] is False


def test_compare_parse_error():
    """Malformed input should return an error."""
    result = json.loads(compare_structures("not json", json.dumps({"objects": []})))
    assert result["equivalent"] is False
    assert "error" in result