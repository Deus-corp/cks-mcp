"""Tests for validate_knowledge tool."""
import json

from cks_mcp.tools.validate import validate_knowledge


def test_validate_valid_structure():
    """A valid minimal structure should pass validation."""
    valid_json = json.dumps({
        "objects": [
            {
                "identity": {"id": "obj-1", "type": "Definition", "name": "Test"},
                "structure": {},
            }
        ]
    })
    result = json.loads(validate_knowledge(valid_json))
    assert result["valid"] is True
    assert result["error_count"] == 0


def test_validate_invalid_structure():
    """An invalid structure (duplicate IDs) should fail."""
    invalid_json = json.dumps({
        "objects": [
            {"identity": {"id": "dup", "type": "Definition", "name": "First"}, "structure": {}},
            {"identity": {"id": "dup", "type": "Definition", "name": "Second"}, "structure": {}},
        ]
    })
    result = json.loads(validate_knowledge(invalid_json))
    assert result["valid"] is False
    # Should be a parse error (duplicate identity detected by parser)
    assert "Duplicate" in result.get("error", "")


def test_validate_malformed_json():
    """Malformed JSON should return an error."""
    result = json.loads(validate_knowledge("not json"))
    assert result["valid"] is False
    assert "error" in result