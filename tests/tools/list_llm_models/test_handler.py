"""Unit tests for the list_llm_models MCP tool."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from cks_mcp.tools.list_llm_models.cache import list_llm_models_cache
from cks_mcp.tools.list_llm_models.handler import list_llm_models

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_list_llm_models_cache():
    list_llm_models_cache.clear()
    yield
    list_llm_models_cache.clear()


@pytest.fixture
def mock_runtime():
    return MagicMock()


def _patched(env: dict[str, str], ollama_available: bool):
    return (
        patch.dict("os.environ", env, clear=True),
        patch(
            "cks_mcp.tools.list_llm_models.handler.llm_providers.ollama_available",
            return_value=ollama_available,
        ),
    )


# ---------------------------------------------------------------------------
# 'auto' resolution (no explicit CKS_LLM_PROVIDER)
# ---------------------------------------------------------------------------


async def test_auto_prefers_ollama_when_reachable(mock_runtime):
    env_patch, ollama_patch = _patched({}, True)
    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps(
        {"models": [{"name": "llama3.2:latest"}, {"name": "mistral:latest"}]}
    ).encode("utf-8")
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = False

    with env_patch, ollama_patch, patch(
        "cks_mcp.tools.list_llm_models.handler.urllib.request.urlopen",
        return_value=fake_response,
    ):
        result = await list_llm_models(mock_runtime, {})

    assert result == {
        "provider": "ollama",
        "models": [{"name": "llama3.2:latest"}, {"name": "mistral:latest"}],
    }


async def test_ollama_fetch_failure_returns_empty_models(mock_runtime):
    env_patch, ollama_patch = _patched({}, True)

    with env_patch, ollama_patch, patch(
        "cks_mcp.tools.list_llm_models.handler.urllib.request.urlopen",
        side_effect=OSError("boom"),
    ):
        result = await list_llm_models(mock_runtime, {})

    assert result == {"provider": "ollama", "models": []}


async def test_auto_falls_back_to_anthropic_when_ollama_unreachable(mock_runtime):
    env_patch, ollama_patch = _patched({"ANTHROPIC_API_KEY": "sk-test"}, False)
    with env_patch, ollama_patch:
        result = await list_llm_models(mock_runtime, {})

    assert result == {
        "provider": "anthropic",
        "models": [
            {"name": "claude-sonnet-4-5-20250929"},
            {"name": "claude-opus-4-1-20250805"},
            {"name": "claude-haiku-3-5-20241022"},
        ],
    }


async def test_auto_none_when_nothing_configured(mock_runtime):
    env_patch, ollama_patch = _patched({}, False)
    with env_patch, ollama_patch:
        result = await list_llm_models(mock_runtime, {})

    assert result == {"provider": "none", "models": []}


# ---------------------------------------------------------------------------
# Explicit CKS_LLM_PROVIDER
# ---------------------------------------------------------------------------


async def test_explicit_openai_compatible(mock_runtime):
    env_patch, ollama_patch = _patched(
        {"CKS_LLM_PROVIDER": "openai_compatible"}, True
    )
    with env_patch, ollama_patch:
        result = await list_llm_models(mock_runtime, {})

    assert result == {
        "provider": "openai_compatible",
        "models": [
            {"name": "gpt-4o"},
            {"name": "gpt-4o-mini"},
            {"name": "gpt-4-turbo"},
            {"name": "gpt-3.5-turbo"},
        ],
    }


async def test_explicit_anthropic_wins_over_reachable_ollama(mock_runtime):
    env_patch, ollama_patch = _patched(
        {"CKS_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "sk-test"}, True
    )
    with env_patch, ollama_patch:
        result = await list_llm_models(mock_runtime, {})

    assert result["provider"] == "anthropic"
    assert {"name": "claude-sonnet-4-5-20250929"} in result["models"]
