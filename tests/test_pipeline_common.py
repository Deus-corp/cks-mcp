"""Unit tests for cks_mcp.pipeline.common."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from cks_mcp.pipeline.common import call_llm, content_hash, find_object

pytestmark = pytest.mark.asyncio


def _make_obj(object_id="obj-1", structure=None):
    return SimpleNamespace(
        identity=SimpleNamespace(id=object_id, name="Widget", type="Concept"),
        structure=structure or {},
    )


def _make_session(objects):
    return SimpleNamespace(knowledge_structure=SimpleNamespace(objects=objects))


async def test_find_object_returns_matching_object():
    obj = _make_obj("obj-1")
    other = _make_obj("obj-2")
    session = _make_session([other, obj])
    assert find_object(session, "obj-1") is obj


async def test_find_object_returns_none_when_missing():
    session = _make_session([_make_obj("obj-1")])
    assert find_object(session, "does-not-exist") is None


async def test_find_object_uses_structure_get_when_available():
    """KnowledgeStructure exposes an O(1) id -> object index via
    ``.get()`` (see cks.core.KnowledgeStructure.get) -- find_object
    must prefer it over scanning ``.objects`` when it's there."""
    obj = _make_obj("obj-1")
    get = MagicMock(return_value=obj)
    structure = SimpleNamespace(get=get, objects=(obj,))
    session = SimpleNamespace(knowledge_structure=structure)

    result = find_object(session, "obj-1")

    assert result is obj
    get.assert_called_once_with("obj-1")


async def test_content_hash_excludes_pipeline_bookkeeping_fields():
    with_bookkeeping = _make_obj(
        structure={
            "color": "blue",
            "current_status": "awaiting_review",
            "transition_log": [{"agent": "ResearcherAgent"}],
        }
    )
    without_bookkeeping = _make_obj(structure={"color": "blue"})
    assert content_hash(with_bookkeeping) == content_hash(without_bookkeeping)


async def test_content_hash_changes_with_real_content():
    obj_a = _make_obj(structure={"color": "blue"})
    obj_b = _make_obj(structure={"color": "red"})
    assert content_hash(obj_a) != content_hash(obj_b)


async def test_call_llm_dispatches_to_anthropic_by_default(monkeypatch):
    monkeypatch.setattr("cks_mcp.pipeline.common.llm_providers.ollama_available", lambda: False)
    fake_call = MagicMock(return_value="the response")
    monkeypatch.setattr("cks_mcp.pipeline.common.llm_providers.call_anthropic", fake_call)

    text, _model = call_llm(
        "a prompt",
        system_prompt="sys",
        tool_name="pipeline_test_step",
        model=None,
        max_tokens=64,
    )

    assert text == "the response"
    fake_call.assert_called_once()
    _, kwargs = fake_call.call_args
    assert kwargs["system_prompt"] == "sys"
    assert kwargs["tool_name"] == "pipeline_test_step"
    assert kwargs["max_tokens"] == 64


async def test_call_llm_dispatches_to_ollama_when_provider_env_set(monkeypatch):
    monkeypatch.setenv("CKS_LLM_PROVIDER", "ollama")
    fake_call = MagicMock(return_value="local response")
    monkeypatch.setattr("cks_mcp.pipeline.common.llm_providers.call_ollama", fake_call)

    text, _model = call_llm(
        "a prompt",
        system_prompt="sys",
        tool_name="pipeline_test_step",
        model=None,
        max_tokens=64,
    )

    assert text == "local response"
    fake_call.assert_called_once()


async def test_call_llm_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("CKS_LLM_PROVIDER", "not-a-real-provider")
    monkeypatch.setattr("cks_mcp.pipeline.common.llm_providers.ollama_available", lambda: False)

    with pytest.raises(RuntimeError, match="Unknown CKS_LLM_PROVIDER"):
        call_llm(
            "a prompt",
            system_prompt="sys",
            tool_name="pipeline_test_step",
            model=None,
            max_tokens=64,
        )