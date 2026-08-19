"""list_llm_models: list the models available for whichever LLM provider
ai_chat/construct_knowledge would currently use (cks-mcp).

Exists so a thin client like cks-studio's AI Chat panel can offer a model
picker before calling ``ai_chat`` with its optional ``model`` argument,
without ever talking to Ollama/Anthropic/OpenAI-compatible endpoints
itself (see cks-studio ADR: Studio never talks to those endpoints
directly, only through cks-mcp tools).

Provider resolution mirrors ``get_llm_status`` exactly (same
``CKS_LLM_PROVIDER=auto|ollama|anthropic|openai_compatible`` precedence)
so the model list this tool returns always matches the provider
``get_llm_status`` reports -- a client polling both never sees them
disagree.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.llm import providers as llm_providers
from cks_mcp.tools.list_llm_models.cache import list_llm_models_cache

_logger = logging.getLogger(__name__)

# Same explicit-provider set as get_llm_status; anything else (unset,
# empty, "auto", or a typo) falls through to availability-based
# detection below.
_EXPLICIT_PROVIDERS = {"ollama", "anthropic", "openai_compatible", "google"}

# Hardcoded model lists for providers with no safe model-list endpoint
# to query without an API key. Kept in sync by hand with get_llm_status's
# default-model fallbacks; revisit when either provider's popular-model
# lineup changes.
_ANTHROPIC_MODELS = [
    "claude-sonnet-4-5-20250929",
    "claude-opus-4-1-20250805",
    "claude-haiku-3-5-20241022",
]
_OPENAI_COMPATIBLE_MODELS = [
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4-turbo",
    "gpt-3.5-turbo",
]
_GOOGLE_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
]


def _fetch_ollama_models() -> list[dict[str, Any]]:
    """GET {CKS_OLLAMA_HOST}/api/tags and return its 'models' list, each
    reduced to {'name': str}. Never raises -- on any failure (network,
    timeout, malformed JSON) returns an empty list, same as
    ollama_available() treating unreachable as a normal outcome rather
    than an error."""
    host = llm_providers.ollama_host()
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=3.0) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        _logger.debug("list_llm_models: Ollama /api/tags fetch failed: %s", exc)
        return []

    raw_models = payload.get("models", []) if isinstance(payload, dict) else []
    models: list[dict[str, Any]] = []
    for entry in raw_models:
        if isinstance(entry, dict) and entry.get("name"):
            models.append({"name": entry["name"]})
    return models


def _cache_key() -> str:
    """Fingerprint the provider config that determines what
    ``list_llm_models`` returns -- provider selection plus whichever
    endpoint URL each provider would be queried against -- so a
    changed config (e.g. pointing at a different Ollama host, or
    flipping CKS_LLM_PROVIDER) always misses the cache, while an
    unchanged config reuses a recent result for
    ``CKS_LLM_MODELS_TTL_SECONDS``. Deliberately excludes API key
    *values* -- only whether each is set -- so a key rotation with
    everything else unchanged still safely reuses the cached model
    list (rotating a key doesn't change which models exist) and no
    key material ever passes through the cache key.
    """
    parts = [
        f"provider={os.environ.get('CKS_LLM_PROVIDER', '').strip().lower()}",
        f"ollama_host={llm_providers.ollama_host()}",
        f"openai_base_url={llm_providers.openai_base_url()}",
        f"anthropic_key_set={bool(os.environ.get('ANTHROPIC_API_KEY', '').strip())}",
        f"openai_key_set={bool(os.environ.get('CKS_OPENAI_API_KEY', '').strip())}",
        f"google_key_set={bool(llm_providers.google_api_key().strip())}",
    ]
    return "|".join(parts)


async def list_llm_models(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Returns::

        {
            "provider": "ollama" | "anthropic" | "openai_compatible" | "none",
            "models": [{"name": str}, ...],
        }

    ``provider`` resolution is identical to ``get_llm_status`` (see that
    handler's docstring): an explicit ``CKS_LLM_PROVIDER`` wins outright,
    otherwise Ollama is preferred if reachable, then Anthropic if
    ``ANTHROPIC_API_KEY`` is set, else ``"none"``.

    For ``"ollama"``, ``models`` comes from a live ``GET
    {CKS_OLLAMA_HOST}/api/tags`` call and reflects whatever's actually
    installed on that server (empty list if the call fails). For
    ``"anthropic"`` and ``"openai_compatible"``, ``models`` is a short
    hardcoded list of current popular models. For ``"none"``, ``models``
    is empty.

    Cached for ``CKS_LLM_MODELS_TTL_SECONDS`` (default 300s) per
    provider-config fingerprint (see ``_cache_key``), so a client like
    cks-studio's Settings page polling this on every render doesn't
    hit the provider (or probe Ollama's reachability) on every single
    call. Set ``CKS_LLM_MODELS_TTL_SECONDS=0`` to disable caching.
    """
    cache_key = _cache_key()
    cached = list_llm_models_cache.get(cache_key)
    if cached is not None:
        return cached

    ollama_reachable = llm_providers.ollama_available()
    anthropic_key_set = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())

    explicit = os.environ.get("CKS_LLM_PROVIDER", "").strip().lower()
    if explicit in _EXPLICIT_PROVIDERS:
        provider = explicit
    elif ollama_reachable:
        provider = "ollama"
    elif anthropic_key_set:
        provider = "anthropic"
    else:
        provider = "none"

    if provider == "ollama":
        models = _fetch_ollama_models()
    elif provider == "anthropic":
        models = [{"name": name} for name in _ANTHROPIC_MODELS]
    elif provider == "openai_compatible":
        models = [{"name": name} for name in _OPENAI_COMPATIBLE_MODELS]
    elif provider == "google":
        models = [{"name": name} for name in _GOOGLE_MODELS]
    else:
        models = []

    result = {
        "provider": provider,
        "models": models,
    }
    # "none" (no provider configured/reachable at all) is intentionally
    # never cached -- it's cheap to recompute (no network call is made
    # for it) and caching it would keep reporting "none" for the full
    # TTL right after the user finishes configuring a provider.
    if provider != "none":
        list_llm_models_cache.set(cache_key, result)
    return result