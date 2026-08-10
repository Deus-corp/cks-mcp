"""get_llm_status: report which LLM provider ai_chat/construct_knowledge
would currently use, and whether it's actually reachable/configured
(cks-mcp ADR-011 §6).

Exists so a thin client like cks-studio's Settings page can show "Local
Ollama" / "Anthropic" / "Not configured" without ever seeing
ANTHROPIC_API_KEY or other provider env vars itself -- those stay
server-side (see cks-studio ADR: Studio never talks to Ollama/Anthropic
directly, only through cks-mcp tools).
"""

from __future__ import annotations

import os
from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp import llm_providers

# Recognized explicit values for CKS_LLM_PROVIDER; anything else (unset,
# empty, "auto", or a typo) falls through to availability-based
# detection below, same as construct_knowledge's _call_llm dispatch.
_EXPLICIT_PROVIDERS = {"ollama", "anthropic"}


async def get_llm_status(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Returns::

        {
            "provider": "ollama" | "anthropic" | "none",
            "ollama_available": bool,
            "anthropic_configured": bool,
            "model": str | None,
        }

    ``provider`` mirrors the resolution construct_knowledge's provider
    router already does for ``CKS_LLM_PROVIDER=auto|ollama|anthropic``
    (see that tool's handler.py): an explicit ``ollama``/``anthropic``
    value wins outright (even if that provider then turns out to be
    unreachable/unconfigured -- ``ollama_available`` /
    ``anthropic_configured`` still tell the caller whether it'll
    actually work); otherwise Ollama is preferred if reachable, then
    Anthropic if ``ANTHROPIC_API_KEY`` is set, else ``"none"``.

    ``ollama_available`` reuses ``llm_providers.ollama_available()`` --
    the same reachability probe (GET ``{CKS_OLLAMA_HOST}/api/tags``)
    every other tool's 'auto' provider selection already relies on --
    rather than a separate GET ``/`` probe, so this tool can never
    report "available" while the actual provider router would still
    treat Ollama as unreachable, or vice versa.

    Read-only: makes no calls to either provider's chat/completion
    endpoints, only a cheap reachability check.
    """
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
        model: str | None = os.environ.get("CKS_OLLAMA_MODEL", "llama3.2")
    elif provider == "anthropic":
        model = os.environ.get("CKS_ANTHROPIC_MODEL") or os.environ.get(
            "CKS_LLM_MODEL", "claude-sonnet-4-5-20250929"
        )
    else:
        model = None

    return {
        "provider": provider,
        "ollama_available": ollama_reachable,
        "anthropic_configured": anthropic_key_set,
        "model": model,
    }
