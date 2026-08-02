"""Unit tests for the evolve MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

VALID_KNOWLEDGE_JSON = (
    '{"objects":[{"identity":{"id":"obj-1","type":"Definition","name":"Test"},"structure":{}}]}'
)

from cks_mcp.tools.evolve.handler import evolve_knowledge

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.core_bridge.validate.return_value = MagicMock(
        valid=True, diagnostics=[], metadata={}
    )
    runtime.core_bridge.serialize.return_value = '{"serialized":true}'
    runtime.core_bridge.explain.return_value = {
        "object_count": 1,
        "relation_count": 0,
        "summary": {"test": True},
    }
    # For evolve_knowledge, core_bridge.evolve must return an object with
    # .relations() (called by provenance).
    fake_evolved = MagicMock()
    fake_evolved.relations.return_value = []
    fake_evolved.objects = []
    runtime.core_bridge.evolve.return_value = fake_evolved

    session = MagicMock(session_id="s1", diagnostics=[])
    runtime.create_session = AsyncMock(return_value=session)

    tx = MagicMock(session=session)
    tx.results = [MagicMock(payload='{"serialized":true}')]
    runtime.begin_transaction.return_value = tx

    runtime.commit_transaction = AsyncMock(return_value=MagicMock(version_id="v1"))
    runtime.executor.execute = AsyncMock(return_value=MagicMock(
        succeeded=True,
        payload=fake_evolved,
        status=MagicMock(value="completed")
    ))

    return runtime



async def test_evolve_knowledge(mock_runtime):
    args = {
        "json_data": VALID_KNOWLEDGE_JSON,
        "operations": [
            {
                "type": "add_object",
                "identity": {"id": "obj-2", "type": "Lemma", "name": "New"},
                "structure": {},
            }
        ],
    }
    result = await evolve_knowledge(mock_runtime, args)
    assert result["evolved"] == True
    assert result["version_id"] == "v1"
    assert result["session_id"] == "s1"
    mock_runtime.create_session.assert_awaited_once()
    mock_runtime.commit_transaction.assert_awaited_once()


# ---------------------------------------------------------------------------
# resolve_inference_conflict + 'extensions' opt-in (see cks-core ADR-001/
# ADR-002 and validate_knowledge's own 'extensions' parameter). Uses a real
# Runtime rather than mock_runtime: the mock's core_bridge.evolve always
# returns a canned empty MagicMock, which can't exercise an actual
# InferenceStep supersession or a real commit-time constraint failure.
# ---------------------------------------------------------------------------


def _real_runtime():
    from cks_runtime.runtime import Runtime
    from cks_runtime_plugins.cks_core import CksCoreAdapter
    return Runtime(core=CksCoreAdapter())


def _two_step_conflict_json() -> str:
    import json

    return json.dumps(
        {
            "objects": [
                {
                    "identity": {"id": "c1", "type": "Claim", "name": "Conclusion"},
                    "structure": {},
                },
                {
                    "identity": {"id": "step-a", "type": "InferenceStep", "name": "A"},
                    "structure": {
                        "premises": [],
                        "conclusion": "c1",
                        "confidence": 0.9,
                    },
                },
                {
                    "identity": {"id": "step-b", "type": "InferenceStep", "name": "B"},
                    "structure": {
                        "premises": [],
                        "conclusion": "c1",
                        "confidence": 0.4,
                    },
                },
            ]
        }
    )


async def test_resolve_inference_conflict_supersedes_the_loser():
    import json

    runtime = _real_runtime()
    result = await evolve_knowledge(
        runtime,
        {
            "json_data": _two_step_conflict_json(),
            "operations": [
                {
                    "type": "resolve_inference_conflict",
                    "conclusion_id": "c1",
                    "winner_id": "step-a",
                }
            ],
            "extensions": ["supersession_chain", "inference_confidence_conflict"],
        },
    )
    assert result.get("evolved") is True
    objs = {o["identity"]["id"]: o for o in json.loads(result["serialized"])["objects"]}
    assert objs["step-b"]["structure"].get("superseded_by") == "step-a"
    assert "superseded_by" not in objs["step-a"]["structure"]
    assert result["extensions_applied"] == [
        "supersession_chain",
        "inference_confidence_conflict",
    ]


async def test_resolve_inference_conflict_rejects_nonexistent_winner():
    runtime = _real_runtime()
    result = await evolve_knowledge(
        runtime,
        {
            "json_data": _two_step_conflict_json(),
            "operations": [
                {
                    "type": "resolve_inference_conflict",
                    "conclusion_id": "c1",
                    "winner_id": "does-not-exist",
                }
            ],
        },
    )
    assert "error" in result
    assert "does not exist" in result["error"]


async def test_evolve_knowledge_unknown_extension_is_rejected():
    runtime = _real_runtime()
    result = await evolve_knowledge(
        runtime,
        {
            "json_data": VALID_KNOWLEDGE_JSON,
            "operations": [
                {"type": "rename_object", "object_id": "obj-1", "new_name": "Renamed"}
            ],
            "extensions": ["not_a_real_extension"],
        },
    )
    assert result["error"] == "unknown_extension"


async def test_evolve_knowledge_without_extensions_does_not_check_confidence_bounds():

    runtime = _real_runtime()
    result = await evolve_knowledge(
        runtime,
        {
            "json_data": _two_step_conflict_json(),
            "operations": [
                {
                    "type": "update_object",
                    "object_id": "step-a",
                    "structure_patch": {"confidence": 1.5},
                }
            ],
        },
    )
    # Built-in constraints alone never look at InferenceStep.confidence,
    # so this commits despite the out-of-range value -- the exact gap
    # 'extensions' now lets a caller close for this call.
    assert result.get("evolved") is True
    assert "extensions_applied" not in result


async def test_evolve_knowledge_with_confidence_bounds_extension_rejects_it():
    runtime = _real_runtime()
    result = await evolve_knowledge(
        runtime,
        {
            "json_data": _two_step_conflict_json(),
            "operations": [
                {
                    "type": "update_object",
                    "object_id": "step-a",
                    "structure_patch": {"confidence": 1.5},
                }
            ],
            "extensions": ["confidence_bounds"],
        },
    )
    assert result["error"] == "validation_failed"
    assert any(d["code"] == "CKS-EXT-CONFIDENCE-BOUNDS" for d in result["diagnostics"])