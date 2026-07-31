"""
Tests for _call_llm provider dispatch (Ollama / Anthropic / auto fallback).
"""

from unittest.mock import patch

import pytest

from cks_mcp.tools.construct_knowledge.handler import _call_llm


def _sanitized_env(monkeypatch):
    """Remove all LLM-provider env vars so tests start from a clean slate."""
    for key in (
        "ANTHROPIC_API_KEY",
        "CKS_LLM_PROVIDER",
        "CKS_OLLAMA_HOST",
        "CKS_OLLAMA_MODEL",
        "CKS_LLM_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_auto_provider_prefers_ollama_when_reachable(monkeypatch):
    """With no explicit provider and Ollama reachable, auto selects Ollama."""
    _sanitized_env(monkeypatch)
    monkeypatch.setattr(
        "cks_mcp.tools.construct_knowledge.handler._ollama_available",
        lambda host=None: True,
    )

    with patch(
        "cks_mcp.tools.construct_knowledge.handler._call_ollama",
        return_value='{"objects": []}',
    ) as mock_ollama:
        _call_llm("test prompt", model=None, max_tokens=100)

    mock_ollama.assert_called_once()


def test_auto_provider_falls_back_to_anthropic_when_ollama_unreachable(monkeypatch):
    """When Ollama is down but ANTHROPIC_API_KEY is set, auto selects Anthropic."""
    _sanitized_env(monkeypatch)
    monkeypatch.setattr(
        "cks_mcp.tools.construct_knowledge.handler._ollama_available",
        lambda host=None: False,
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

    with patch(
        "cks_mcp.tools.construct_knowledge.handler._call_anthropic",
        return_value='{"objects": []}',
    ) as mock_anthropic:
        _call_llm("test prompt", model=None, max_tokens=100)

    mock_anthropic.assert_called_once()


def test_no_provider_available_raises_clear_error(monkeypatch):
    """When neither Ollama nor Anthropic is available, a descriptive RuntimeError
    is raised listing all three options (local, Anthropic, DIY)."""
    _sanitized_env(monkeypatch)
    monkeypatch.setattr(
        "cks_mcp.tools.construct_knowledge.handler._ollama_available",
        lambda host=None: False,
    )
    # ANTHROPIC_API_KEY is already unset (sanitised)

    with pytest.raises(RuntimeError, match="No LLM provider available"):
        _call_llm("test prompt", model=None, max_tokens=100)