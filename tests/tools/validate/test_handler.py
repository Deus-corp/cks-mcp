"""Unit tests for the validate MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

VALID_KNOWLEDGE_JSON = (
    '{"objects":[{"identity":{"id":"obj-1","type":"Definition","name":"Test"},"structure":{}}]}'
)

from cks_mcp.tools.validate.handler import validate_knowledge

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



async def test_validate_knowledge_valid(mock_runtime):
    args = {"json_data": VALID_KNOWLEDGE_JSON}
    result = await validate_knowledge(mock_runtime, args)
    assert result["valid"] == True
    assert result["version_id"] == "v1"
    assert result["session_id"] == "s1"
    mock_runtime.create_session.assert_awaited_once()
    mock_runtime.commit_transaction.assert_awaited_once()


async def test_validate_knowledge_invalid(mock_runtime):
    from cks_runtime.diagnostics.diagnostic import (
        Diagnostic as RuntimeDiagnostic,
    )
    from cks_runtime.diagnostics.diagnostic import (
        DiagnosticSeverity,
        DiagnosticSource,
    )

    session = MagicMock(diagnostics=[], session_id="s1")
    mock_runtime.create_session = AsyncMock(return_value=session)
    tx = MagicMock(session=session)
    mock_runtime.begin_transaction.return_value = tx

    async def fake_commit(tx):
        tx.session.diagnostics.append(
            RuntimeDiagnostic(
                code="ERR-001",
                severity=DiagnosticSeverity.ERROR,
                source=DiagnosticSource.CORE,
                message="Invalid structure",
                metadata={"key": "value"},
            )
        )
        return MagicMock(version_id="v2")

    mock_runtime.commit_transaction = AsyncMock(side_effect=fake_commit)
    mock_runtime.executor.execute = AsyncMock(return_value=MagicMock(
        succeeded=True,
        payload={"evolved": True},
        status=MagicMock(value="completed")
    ))
    args = {"json_data": VALID_KNOWLEDGE_JSON}
    result = await validate_knowledge(mock_runtime, args)
    assert result["valid"] is False
    assert result["version_id"] == "v2"
    assert len(result["diagnostics"]) == 1
    assert result["diagnostics"][0]["code"] == "ERR-001"
    assert result["diagnostics"][0]["severity"] == "error"


# ---------------------------------------------------------------------------
# Reasoning-domain extensions (see cks-core ADR-001). These were registered
# in cks-core's OPTIONAL_CONSTRAINTS_BY_NAME but never wired into this
# module's EXTENSION_ALIASES, so they could not be resolved by name at all
# before this fix -- every call with e.g. 'confidence_bounds' returned
# unknown_extension regardless of the structure's content.
# ---------------------------------------------------------------------------


def _real_runtime():
    from cks_runtime.runtime import Runtime
    from cks_runtime_plugins.cks_core import CksCoreAdapter
    return Runtime(core=CksCoreAdapter())


@pytest.mark.parametrize(
    "extension_name",
    [
        "inference_referential_integrity",
        "confidence_bounds",
        "supersession_chain",
        "inference_confidence_conflict",
    ],
)
async def test_reasoning_extensions_resolve_by_name(extension_name):
    runtime = _real_runtime()
    result = await validate_knowledge(runtime, {
        "json_data": '{"objects": [{"identity": {"id": "obj-1", "type": "InferenceStep", '
        '"name": "s"}, "structure": {}}]}',
        "extensions": [extension_name],
    })
    assert result.get("error") != "unknown_extension"
    assert result["extensions_applied"] == [extension_name]


async def test_confidence_bounds_extension_actually_fires_when_resolved():
    runtime = _real_runtime()
    result = await validate_knowledge(runtime, {
        "json_data": '{"objects": [{"identity": {"id": "step-1", "type": "InferenceStep", '
        '"name": "s"}, "structure": {"conclusion": "c1", "confidence": 1.5}}]}',
        "extensions": ["confidence_bounds"],
    })
    assert result["valid"] is False
    assert any(d["code"] == "CKS-EXT-CONFIDENCE-BOUNDS" for d in result["diagnostics"])
