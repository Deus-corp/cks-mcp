"""Unit tests for the get_llm_status MCP tool (cks-mcp ADR-011 §6)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cks_mcp.tools.get_llm_status.handler import get_llm_status

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_runtime():
    return MagicMock()


def _patched(env: dict[str, str], ollama_available: bool):
    return (
        patch.dict("os.environ", env, clear=True),
        patch(
            "cks_mcp.tools.get_llm_status.handler.llm_providers.ollama_available",
            return_value=ollama_available,
        ),
    )


# ---------------------------------------------------------------------------
# 'auto' resolution (no explicit CKS_LLM_PROVIDER)
# ---------------------------------------------------------------------------


async def test_auto_prefers_ollama_when_reachable_even_with_anthropic_key(mock_runtime):
    env_patch, ollama_patch = _patched({"ANTHROPIC_API_KEY": "sk-test"}, True)
    with env_patch, ollama_patch:
        result = await get_llm_status(mock_runtime, {})

    assert result == {
        "provider": "ollama",
        "ollama_available": True,
        "anthropic_configured": True,
        "openai_compatible_configured": False,
        "google_configured": False,
        "model": "llama3.2",
    }


async def test_auto_falls_back_to_anthropic_when_ollama_unreachable(mock_runtime):
    env_patch, ollama_patch = _patched({"ANTHROPIC_API_KEY": "sk-test"}, False)
    with env_patch, ollama_patch:
        result = await get_llm_status(mock_runtime, {})

    assert result == {
        "provider": "anthropic",
        "ollama_available": False,
        "anthropic_configured": True,
        "openai_compatible_configured": False,
        "google_configured": False,
        "model": "claude-sonnet-4-5-20250929",
    }


async def test_auto_reports_none_when_nothing_available_or_configured(mock_runtime):
    env_patch, ollama_patch = _patched({}, False)
    with env_patch, ollama_patch:
        result = await get_llm_status(mock_runtime, {})

    assert result == {
        "provider": "none",
        "ollama_available": False,
        "anthropic_configured": False,
        "openai_compatible_configured": False,
        "google_configured": False,
        "model": None,
    }


async def test_empty_anthropic_api_key_counts_as_not_configured(mock_runtime):
    env_patch, ollama_patch = _patched({"ANTHROPIC_API_KEY": "   "}, False)
    with env_patch, ollama_patch:
        result = await get_llm_status(mock_runtime, {})

    assert result["anthropic_configured"] is False
    assert result["provider"] == "none"


# ---------------------------------------------------------------------------
# Explicit CKS_LLM_PROVIDER
# ---------------------------------------------------------------------------


async def test_explicit_ollama_wins_even_when_unreachable(mock_runtime):
    # Explicit choice is reported as-is; ollama_available still tells the
    # caller it won't actually work right now.
    env_patch, ollama_patch = _patched(
        {"CKS_LLM_PROVIDER": "ollama", "ANTHROPIC_API_KEY": "sk-test"}, False
    )
    with env_patch, ollama_patch:
        result = await get_llm_status(mock_runtime, {})

    assert result["provider"] == "ollama"
    assert result["ollama_available"] is False
    assert result["model"] == "llama3.2"


async def test_explicit_anthropic_wins_even_when_ollama_reachable(mock_runtime):
    env_patch, ollama_patch = _patched(
        {"CKS_LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "sk-test"}, True
    )
    with env_patch, ollama_patch:
        result = await get_llm_status(mock_runtime, {})

    assert result["provider"] == "anthropic"
    assert result["ollama_available"] is True
    assert result["model"] == "claude-sonnet-4-5-20250929"


async def test_explicit_anthropic_without_key_still_reports_anthropic(mock_runtime):
    env_patch, ollama_patch = _patched({"CKS_LLM_PROVIDER": "anthropic"}, True)
    with env_patch, ollama_patch:
        result = await get_llm_status(mock_runtime, {})

    assert result["provider"] == "anthropic"
    assert result["anthropic_configured"] is False


async def test_unknown_provider_value_falls_through_to_auto_detection(mock_runtime):
    env_patch, ollama_patch = _patched(
        {"CKS_LLM_PROVIDER": "bogus", "ANTHROPIC_API_KEY": "sk-test"}, False
    )
    with env_patch, ollama_patch:
        result = await get_llm_status(mock_runtime, {})

    assert result["provider"] == "anthropic"


async def test_provider_value_is_case_insensitive(mock_runtime):
    env_patch, ollama_patch = _patched({"CKS_LLM_PROVIDER": "OLLAMA"}, True)
    with env_patch, ollama_patch:
        result = await get_llm_status(mock_runtime, {})

    assert result["provider"] == "ollama"


# ---------------------------------------------------------------------------
# Model overrides
# ---------------------------------------------------------------------------


async def test_ollama_model_env_override_is_reflected(mock_runtime):
    env_patch, ollama_patch = _patched(
        {"CKS_LLM_PROVIDER": "ollama", "CKS_OLLAMA_MODEL": "qwen2.5:7b"}, True
    )
    with env_patch, ollama_patch:
        result = await get_llm_status(mock_runtime, {})

    assert result["model"] == "qwen2.5:7b"


async def test_anthropic_model_env_override_is_reflected(mock_runtime):
    env_patch, ollama_patch = _patched(
        {
            "CKS_LLM_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "sk-test",
            "CKS_ANTHROPIC_MODEL": "claude-opus-4-1",
        },
        False,
    )
    with env_patch, ollama_patch:
        result = await get_llm_status(mock_runtime, {})

    assert result["model"] == "claude-opus-4-1"


# ---------------------------------------------------------------------------
# openai_compatible provider
# ---------------------------------------------------------------------------


async def test_explicit_openai_compatible_wins_even_when_ollama_reachable(mock_runtime):
    env_patch, ollama_patch = _patched(
        {"CKS_LLM_PROVIDER": "openai_compatible", "CKS_OPENAI_API_KEY": "sk-fake"}, True
    )
    with env_patch, ollama_patch:
        result = await get_llm_status(mock_runtime, {})

    assert result == {
        "provider": "openai_compatible",
        "ollama_available": True,
        "anthropic_configured": False,
        "openai_compatible_configured": True,
        "google_configured": False,
        "model": "gpt-4o",
    }


async def test_explicit_openai_compatible_without_key_still_reports_openai_compatible(mock_runtime):
    env_patch, ollama_patch = _patched({"CKS_LLM_PROVIDER": "openai_compatible"}, False)
    with env_patch, ollama_patch:
        result = await get_llm_status(mock_runtime, {})

    assert result["provider"] == "openai_compatible"
    assert result["openai_compatible_configured"] is False


async def test_openai_compatible_model_env_override_is_reflected(mock_runtime):
    env_patch, ollama_patch = _patched(
        {
            "CKS_LLM_PROVIDER": "openai_compatible",
            "CKS_OPENAI_API_KEY": "sk-fake",
            "CKS_OPENAI_MODEL": "deepseek-chat",
        },
        False,
    )
    with env_patch, ollama_patch:
        result = await get_llm_status(mock_runtime, {})

    assert result["model"] == "deepseek-chat"


async def test_auto_never_selects_openai_compatible_even_when_configured(mock_runtime):
    # auto-detection must never pick openai_compatible on its own, even if
    # CKS_OPENAI_API_KEY happens to be set -- it requires an explicit
    # CKS_LLM_PROVIDER=openai_compatible, same as every other provider
    # router in cks-mcp.
    env_patch, ollama_patch = _patched(
        {"CKS_OPENAI_API_KEY": "sk-fake", "ANTHROPIC_API_KEY": "sk-test"}, False
    )
    with env_patch, ollama_patch:
        result = await get_llm_status(mock_runtime, {})

    assert result["provider"] == "anthropic"
    assert result["openai_compatible_configured"] is True


async def test_empty_openai_api_key_counts_as_not_configured(mock_runtime):
    env_patch, ollama_patch = _patched(
        {"CKS_LLM_PROVIDER": "openai_compatible", "CKS_OPENAI_API_KEY": "   "}, False
    )
    with env_patch, ollama_patch:
        result = await get_llm_status(mock_runtime, {})

    assert result["openai_compatible_configured"] is False
