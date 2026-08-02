"""Unit tests for the explain MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

VALID_KNOWLEDGE_JSON = (
    '{"objects":[{"identity":{"id":"obj-1","type":"Definition","name":"Test"},"structure":{}}]}'
)

from cks_mcp.tools.explain.handler import explain_knowledge

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



async def test_explain_knowledge(mock_runtime):
    mock_runtime.begin_transaction.return_value.results = [
        MagicMock(payload={"object_count": 1, "relation_count": 0})
    ]
    args = {"json_data": VALID_KNOWLEDGE_JSON}
    result = await explain_knowledge(mock_runtime, args)
    assert result["object_count"] == 1
    assert result["relation_count"] == 0


async def test_explain_knowledge_session_id_without_object_id_uses_explain_operation(
    mock_runtime,
):
    """No object_id -> the general, structure-wide ExplainOperation is used."""
    from cks_runtime.operations.operation_types import ExplainOperation

    mock_runtime.get_session = MagicMock(
        return_value=MagicMock(session_id="s1", knowledge_structure="struct")
    )
    mock_runtime.executor.execute = AsyncMock(
        return_value=MagicMock(
            succeeded=True,
            payload={"object_count": 1},
            status=MagicMock(value="completed"),
        )
    )
    args = {"json_data": VALID_KNOWLEDGE_JSON, "session_id": "s1"}
    result = await explain_knowledge(mock_runtime, args)

    assert result == {"session_id": "s1", "explanation": {"object_count": 1}}
    op = mock_runtime.executor.execute.call_args[0][0]
    assert isinstance(op, ExplainOperation)


async def test_explain_knowledge_session_id_with_object_id_uses_explain_inference(
    mock_runtime,
):
    """object_id given -> routes to ExplainInferenceOperation, not ExplainOperation."""
    from cks_runtime.operations.operation_types import ExplainInferenceOperation

    mock_runtime.get_session = MagicMock(
        return_value=MagicMock(session_id="s1", knowledge_structure="struct")
    )
    payload = {"active_steps": [], "superseded_steps": []}
    mock_runtime.executor.execute = AsyncMock(
        return_value=MagicMock(
            succeeded=True, payload=payload, status=MagicMock(value="completed"), error=None
        )
    )
    args = {"json_data": VALID_KNOWLEDGE_JSON, "session_id": "s1", "object_id": "obj-1"}
    result = await explain_knowledge(mock_runtime, args)

    assert result == {"session_id": "s1", "explanation": payload}
    op = mock_runtime.executor.execute.call_args[0][0]
    assert isinstance(op, ExplainInferenceOperation)
    assert op.object_id == "obj-1"
    assert op.knowledge_structure == "struct"


async def test_explain_knowledge_session_id_with_object_id_failure_reports_error(
    mock_runtime,
):
    """
    Unsupported Core / unknown object_id -> a FAILED ExecutionResult, surfaced
    as internal_error rather than silently swallowed to an empty explanation
    (there's no meaningful empty default for "why").
    """
    mock_runtime.get_session = MagicMock(
        return_value=MagicMock(session_id="s1", knowledge_structure="struct")
    )
    mock_runtime.executor.execute = AsyncMock(
        return_value=MagicMock(
            succeeded=False,
            payload=None,
            status=MagicMock(value="failed"),
            error=NotImplementedError("Core does not implement explain_inference()."),
        )
    )
    args = {"json_data": VALID_KNOWLEDGE_JSON, "session_id": "s1", "object_id": "missing-obj"}
    result = await explain_knowledge(mock_runtime, args)

    assert result["error"] == "internal_error"
    assert "missing-obj" in result["message"]


async def test_explain_knowledge_fallback_with_object_id_uses_explain_inference(
    mock_runtime,
):
    """No session_id but object_id given -> still routes to ExplainInferenceOperation."""
    from cks_runtime.operations.operation_types import ExplainInferenceOperation

    payload = {"active_steps": [], "superseded_steps": []}
    mock_runtime.begin_transaction.return_value.results = [
        MagicMock(payload=payload, succeeded=True)
    ]
    args = {"json_data": VALID_KNOWLEDGE_JSON, "object_id": "obj-1"}
    result = await explain_knowledge(mock_runtime, args)

    assert result == payload
    added_op = mock_runtime.begin_transaction.return_value.add_operation.call_args[0][0]
    assert isinstance(added_op, ExplainInferenceOperation)
    assert added_op.object_id == "obj-1"


async def test_explain_knowledge_fallback_with_object_id_failure_reports_error(
    mock_runtime,
):
    mock_runtime.begin_transaction.return_value.results = [
        MagicMock(payload=None, succeeded=False, error=ValueError("unknown object_id"))
    ]
    args = {"json_data": VALID_KNOWLEDGE_JSON, "object_id": "obj-unknown"}
    result = await explain_knowledge(mock_runtime, args)

    assert result["error"] == "internal_error"
    assert "obj-unknown" in result["message"]
