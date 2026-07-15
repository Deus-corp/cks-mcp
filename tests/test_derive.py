"""Tests for derive_knowledge tool."""
import json
from cks_mcp.tools.derive import derive_knowledge


def test_derive_success():
    """Derive a new object from existing premises."""
    data = json.dumps({
        "objects": [
            {"identity": {"id": "prem-1", "type": "Axiom", "name": "A"}, "structure": {}},
            {"identity": {"id": "prem-2", "type": "Axiom", "name": "B"}, "structure": {}},
        ]
    })
    result = derive_knowledge(
        json_data=data,
        premises=json.dumps(["prem-1", "prem-2"]),
        rule="modus_ponens",
        conclusion_id="conc-1",
        conclusion_type="Theorem",
        conclusion_name="C",
    )
    assert "conc-1" in result


def test_derive_missing_premise():
    """Derivation with missing premise should return an error."""
    data = json.dumps({
        "objects": [
            {"identity": {"id": "prem-1", "type": "Axiom", "name": "A"}, "structure": {}},
        ]
    })
    result = json.loads(derive_knowledge(
        json_data=data,
        premises=json.dumps(["prem-1", "prem-missing"]),
        rule="modus_ponens",
        conclusion_id="conc-1",
        conclusion_type="Theorem",
        conclusion_name="C",
    ))
    assert "error" in result


def test_derive_duplicate_id():
    """Derivation with duplicate conclusion ID should return an error."""
    data = json.dumps({
        "objects": [
            {"identity": {"id": "prem-1", "type": "Axiom", "name": "A"}, "structure": {}},
            {"identity": {"id": "conc-1", "type": "Theorem", "name": "Already exists"}, "structure": {}},
        ]
    })
    result = json.loads(derive_knowledge(
        json_data=data,
        premises=json.dumps(["prem-1"]),
        rule="modus_ponens",
        conclusion_id="conc-1",
        conclusion_type="Theorem",
        conclusion_name="C",
    ))
    assert "error" in result