"""
Tests for the provider-dispatch branches inside
``ingest_document.handler._build_llm_structure`` (ollama / anthropic /
auto fallback / unknown provider).

Mirrors ``tests/tools/construct_knowledge/test_dispatch.py``. This
branching is a separate copy of that dispatch logic (see the comment
in ``_build_llm_structure``), so it needs its own coverage -- the
existing ``test_ingest_structured_with_use_llm`` test in
``test_handler.py`` mocks ``_build_llm_structure`` away entirely and
never exercises any of these branches.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import cks
import pytest

from cks_mcp.tools.ingest_document.handler import _build_llm_structure

_VALID_CKS_JSON = json.dumps(
    {
        "objects": [
            {
                "identity": {"id": "doc-x", "type": "Document", "name": "X"},
                "structure": {},
            }
        ]
    }
)


def _sanitized_env(monkeypatch):
    for key in (
        "ANTHROPIC_API_KEY",
        "CKS_LLM_PROVIDER",
        "CKS_OLLAMA_HOST",
        "CKS_OLLAMA_MODEL",
        "CKS_LLM_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_explicit_ollama_provider_used(monkeypatch):
    _sanitized_env(monkeypatch)
    monkeypatch.setenv("CKS_LLM_PROVIDER", "ollama")

    with patch(
        "cks_mcp.llm_providers.call_ollama", return_value=_VALID_CKS_JSON
    ) as mock_ollama:
        structure, model_used = _build_llm_structure({"title": "T"}, {})

    mock_ollama.assert_called_once()
    assert model_used == "llama3.2"
    assert isinstance(structure, cks.KnowledgeStructure)


def test_explicit_anthropic_provider_used(monkeypatch):
    _sanitized_env(monkeypatch)
    monkeypatch.setenv("CKS_LLM_PROVIDER", "anthropic")

    with patch(
        "cks_mcp.llm_providers.call_anthropic", return_value=_VALID_CKS_JSON
    ) as mock_anthropic:
        structure, model_used = _build_llm_structure({"title": "T"}, {})

    mock_anthropic.assert_called_once()
    assert model_used == "claude-sonnet-4-6"
    assert isinstance(structure, cks.KnowledgeStructure)


def test_auto_prefers_ollama_when_reachable(monkeypatch):
    _sanitized_env(monkeypatch)
    monkeypatch.setattr(
        "cks_mcp.llm_providers.ollama_available", lambda *a, **kw: True
    )

    with patch(
        "cks_mcp.llm_providers.call_ollama", return_value=_VALID_CKS_JSON
    ) as mock_ollama:
        _build_llm_structure({"title": "T"}, {})

    mock_ollama.assert_called_once()


def test_auto_falls_back_to_anthropic_when_ollama_unreachable(monkeypatch):
    _sanitized_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setattr(
        "cks_mcp.llm_providers.ollama_available", lambda *a, **kw: False
    )

    with patch(
        "cks_mcp.llm_providers.call_anthropic", return_value=_VALID_CKS_JSON
    ) as mock_anthropic:
        _build_llm_structure({"title": "T"}, {})

    mock_anthropic.assert_called_once()


def test_auto_no_provider_available_raises_descriptive_error(monkeypatch):
    _sanitized_env(monkeypatch)
    monkeypatch.setattr(
        "cks_mcp.llm_providers.ollama_available", lambda *a, **kw: False
    )
    # ANTHROPIC_API_KEY intentionally left unset.

    with pytest.raises(RuntimeError, match="No LLM provider available"):
        _build_llm_structure({"title": "T"}, {})


def test_unknown_provider_raises(monkeypatch):
    _sanitized_env(monkeypatch)
    monkeypatch.setenv("CKS_LLM_PROVIDER", "not-a-real-provider")

    with pytest.raises(RuntimeError, match="Unknown CKS_LLM_PROVIDER"):
        _build_llm_structure({"title": "T"}, {})


def test_model_and_max_tokens_overrides_are_forwarded(monkeypatch):
    _sanitized_env(monkeypatch)
    monkeypatch.setenv("CKS_LLM_PROVIDER", "ollama")

    with patch(
        "cks_mcp.llm_providers.call_ollama", return_value=_VALID_CKS_JSON
    ) as mock_ollama:
        _, model_used = _build_llm_structure(
            {"title": "T"}, {"model": "custom-model", "max_tokens": 555}
        )

    assert model_used == "custom-model"
    _, kwargs = mock_ollama.call_args
    assert kwargs["model"] == "custom-model"
    assert kwargs["max_tokens"] == 555
