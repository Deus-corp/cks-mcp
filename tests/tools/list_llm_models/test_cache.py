"""Tests for TTL caching behavior of the list_llm_models tool."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from cks_mcp.tools.list_llm_models.cache import (
    ListLlmModelsCache,
    list_llm_models_cache,
)
from cks_mcp.tools.list_llm_models.handler import list_llm_models


@pytest.fixture(autouse=True)
def _reset_cache():
    list_llm_models_cache.clear()
    yield
    list_llm_models_cache.clear()


@pytest.fixture
def mock_runtime():
    return MagicMock()


def _fake_ollama_response(names: list[str]):
    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps(
        {"models": [{"name": n} for n in names]}
    ).encode("utf-8")
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = False
    return fake_response


# ---------------------------------------------------------------------------
# ListLlmModelsCache unit behavior (fake clock, no handler involved)
# ---------------------------------------------------------------------------


def test_cache_hit_within_ttl():
    clock = {"t": 0.0}
    cache = ListLlmModelsCache(clock=lambda: clock["t"])
    with patch.dict("os.environ", {}, clear=True):
        cache.set("key1", {"provider": "ollama", "models": [{"name": "a"}]})
    assert cache.get("key1") == {"provider": "ollama", "models": [{"name": "a"}]}


def test_cache_miss_after_ttl_expires():
    clock = {"t": 0.0}
    cache = ListLlmModelsCache(clock=lambda: clock["t"])
    with patch.dict("os.environ", {"CKS_LLM_MODELS_TTL_SECONDS": "60"}, clear=True):
        cache.set("key1", {"provider": "ollama", "models": []})
    clock["t"] = 61.0
    assert cache.get("key1") is None


def test_cache_disabled_when_ttl_zero():
    clock = {"t": 0.0}
    cache = ListLlmModelsCache(clock=lambda: clock["t"])
    with patch.dict("os.environ", {"CKS_LLM_MODELS_TTL_SECONDS": "0"}, clear=True):
        cache.set("key1", {"provider": "ollama", "models": []})
    assert cache.get("key1") is None


def test_different_keys_are_independent():
    cache = ListLlmModelsCache()
    with patch.dict("os.environ", {}, clear=True):
        cache.set("a", {"provider": "ollama", "models": []})
    assert cache.get("b") is None
    assert cache.get("a") is not None


# ---------------------------------------------------------------------------
# End-to-end: list_llm_models handler actually uses the cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_call_within_ttl_skips_provider_call(mock_runtime):
    with patch.dict("os.environ", {}, clear=True), patch(
        "cks_mcp.tools.list_llm_models.handler.llm_providers.ollama_available",
        return_value=True,
    ), patch(
        "cks_mcp.tools.list_llm_models.handler.urllib.request.urlopen",
        return_value=_fake_ollama_response(["llama3.2:latest"]),
    ) as mock_urlopen:
        first = await list_llm_models(mock_runtime, {})
        second = await list_llm_models(mock_runtime, {})

    assert first == second == {
        "provider": "ollama",
        "models": [{"name": "llama3.2:latest"}],
    }
    # Only the first call should have actually hit the network.
    assert mock_urlopen.call_count == 1


@pytest.mark.asyncio
async def test_different_provider_config_invalidates_cache(mock_runtime):
    with patch(
        "cks_mcp.tools.list_llm_models.handler.llm_providers.ollama_available",
        return_value=True,
    ), patch(
        "cks_mcp.tools.list_llm_models.handler.urllib.request.urlopen",
        return_value=_fake_ollama_response(["llama3.2:latest"]),
    ) as mock_urlopen:
        with patch.dict("os.environ", {"CKS_OLLAMA_HOST": "http://host-a:11434"}, clear=True):
            await list_llm_models(mock_runtime, {})
        with patch.dict("os.environ", {"CKS_OLLAMA_HOST": "http://host-b:11434"}, clear=True):
            await list_llm_models(mock_runtime, {})

    # Different CKS_OLLAMA_HOST -> different cache key -> two real calls.
    assert mock_urlopen.call_count == 2


@pytest.mark.asyncio
async def test_missing_provider_not_cached(mock_runtime):
    with patch.dict("os.environ", {}, clear=True), patch(
        "cks_mcp.tools.list_llm_models.handler.llm_providers.ollama_available",
        return_value=False,
    ):
        first = await list_llm_models(mock_runtime, {})
        second = await list_llm_models(mock_runtime, {})

    assert first == second == {"provider": "none", "models": []}
    # "none" results are never written to the cache.
    assert list_llm_models_cache.get(
        "provider=|ollama_host=http://localhost:11434|"
        "openai_base_url=https://api.openai.com/v1|"
        "anthropic_key_set=False|openai_key_set=False"
    ) is None
