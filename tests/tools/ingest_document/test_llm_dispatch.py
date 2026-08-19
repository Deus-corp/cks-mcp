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
        "cks_mcp.llm.providers.call_ollama", return_value=_VALID_CKS_JSON
    ) as mock_ollama:
        structure, model_used = _build_llm_structure({"title": "T"}, {})

    mock_ollama.assert_called_once()
    assert model_used == "llama3.2"
    assert isinstance(structure, cks.KnowledgeStructure)


def test_explicit_anthropic_provider_used(monkeypatch):
    _sanitized_env(monkeypatch)
    monkeypatch.setenv("CKS_LLM_PROVIDER", "anthropic")

    with patch(
        "cks_mcp.llm.providers.call_anthropic", return_value=_VALID_CKS_JSON
    ) as mock_anthropic:
        structure, model_used = _build_llm_structure({"title": "T"}, {})

    mock_anthropic.assert_called_once()
    assert model_used == "claude-sonnet-4-6"
    assert isinstance(structure, cks.KnowledgeStructure)


def test_auto_prefers_ollama_when_reachable(monkeypatch):
    _sanitized_env(monkeypatch)
    monkeypatch.setattr(
        "cks_mcp.llm.providers.ollama_available", lambda *a, **kw: True
    )

    with patch(
        "cks_mcp.llm.providers.call_ollama", return_value=_VALID_CKS_JSON
    ) as mock_ollama:
        _build_llm_structure({"title": "T"}, {})

    mock_ollama.assert_called_once()


def test_auto_falls_back_to_anthropic_when_ollama_unreachable(monkeypatch):
    _sanitized_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setattr(
        "cks_mcp.llm.providers.ollama_available", lambda *a, **kw: False
    )

    with patch(
        "cks_mcp.llm.providers.call_anthropic", return_value=_VALID_CKS_JSON
    ) as mock_anthropic:
        _build_llm_structure({"title": "T"}, {})

    mock_anthropic.assert_called_once()


def test_auto_no_provider_available_raises_descriptive_error(monkeypatch):
    _sanitized_env(monkeypatch)
    monkeypatch.setattr(
        "cks_mcp.llm.providers.ollama_available", lambda *a, **kw: False
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
        "cks_mcp.llm.providers.call_ollama", return_value=_VALID_CKS_JSON
    ) as mock_ollama:
        _, model_used = _build_llm_structure(
            {"title": "T"}, {"model": "custom-model", "max_tokens": 555}
        )

    assert model_used == "custom-model"
    _, kwargs = mock_ollama.call_args
    assert kwargs["model"] == "custom-model"
    assert kwargs["max_tokens"] == 555


def test_explicit_openai_compatible_provider_used(monkeypatch):
    _sanitized_env(monkeypatch)
    monkeypatch.delenv("CKS_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CKS_OPENAI_MODEL", raising=False)
    monkeypatch.setenv("CKS_LLM_PROVIDER", "openai_compatible")

    with patch(
        "cks_mcp.llm.providers.call_openai_compatible_single_shot",
        return_value=_VALID_CKS_JSON,
    ) as mock_openai:
        structure, model_used = _build_llm_structure({"title": "T"}, {})

    mock_openai.assert_called_once()
    assert model_used == "gpt-4o"
    assert isinstance(structure, cks.KnowledgeStructure)


def test_explicit_google_provider_used(monkeypatch):
    _sanitized_env(monkeypatch)
    monkeypatch.delenv("CKS_GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("CKS_GOOGLE_MODEL", raising=False)
    monkeypatch.setenv("CKS_LLM_PROVIDER", "google")

    with patch(
        "cks_mcp.llm.providers.call_google", return_value=_VALID_CKS_JSON
    ) as mock_google:
        structure, model_used = _build_llm_structure({"title": "T"}, {})

    mock_google.assert_called_once()
    assert model_used == "gemini-2.5-flash"
    assert isinstance(structure, cks.KnowledgeStructure)


def test_google_model_env_override_is_reflected(monkeypatch):
    _sanitized_env(monkeypatch)
    monkeypatch.setenv("CKS_LLM_PROVIDER", "google")
    monkeypatch.setenv("CKS_GOOGLE_MODEL", "gemini-2.5-pro")

    with patch(
        "cks_mcp.llm.providers.call_google", return_value=_VALID_CKS_JSON
    ) as mock_google:
        _, model_used = _build_llm_structure({"title": "T"}, {})

    assert model_used == "gemini-2.5-pro"
    _, kwargs = mock_google.call_args
    assert kwargs["model"] == "gemini-2.5-pro"


def test_auto_never_selects_google_when_ollama_unreachable(monkeypatch):
    _sanitized_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setenv("CKS_GOOGLE_API_KEY", "fake-google-key")
    monkeypatch.setattr(
        "cks_mcp.llm.providers.ollama_available", lambda *a, **kw: False
    )

    with patch(
        "cks_mcp.llm.providers.call_anthropic", return_value=_VALID_CKS_JSON
    ) as mock_anthropic, patch(
        "cks_mcp.llm.providers.call_google"
    ) as mock_google:
        _build_llm_structure({"title": "T"}, {})

    mock_anthropic.assert_called_once()
    mock_google.assert_not_called()


def test_auto_never_selects_openai_compatible_when_ollama_unreachable(monkeypatch):
    _sanitized_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
    monkeypatch.setenv("CKS_OPENAI_API_KEY", "fake-openai-key")
    monkeypatch.setattr(
        "cks_mcp.llm.providers.ollama_available", lambda *a, **kw: False
    )

    with patch(
        "cks_mcp.llm.providers.call_anthropic", return_value=_VALID_CKS_JSON
    ) as mock_anthropic, patch(
        "cks_mcp.llm.providers.call_openai_compatible_single_shot"
    ) as mock_openai:
        _build_llm_structure({"title": "T"}, {})

    mock_anthropic.assert_called_once()
    mock_openai.assert_not_called()


def test_auto_no_provider_available_error_mentions_google_and_openai(monkeypatch):
    _sanitized_env(monkeypatch)
    monkeypatch.setattr(
        "cks_mcp.llm.providers.ollama_available", lambda *a, **kw: False
    )

    with pytest.raises(RuntimeError, match="CKS_GOOGLE_API_KEY") as exc_info:
        _build_llm_structure({"title": "T"}, {})
    assert "openai_compatible" in str(exc_info.value)


def test_unknown_provider_message_lists_google_and_openai_compatible(monkeypatch):
    _sanitized_env(monkeypatch)
    monkeypatch.setenv("CKS_LLM_PROVIDER", "not-a-real-provider")

    with pytest.raises(RuntimeError, match="Unknown CKS_LLM_PROVIDER") as exc_info:
        _build_llm_structure({"title": "T"}, {})
    assert "google" in str(exc_info.value)
    assert "openai_compatible" in str(exc_info.value)
