"""
resolve_gossip_conflict: LLM-assisted resolution of structural gossip
merge conflicts -- the counterpart to arbitrate_inference_conflict for
gossip conflicts, closing the asymmetry where gossip conflicts required
hand-rolled resolutions while inference conflicts had LLM assistance.

Session existence/open-state validation is handled by this tool's
registry.py middleware (require_open_session on both target_session_id
and source_session_id), matching merge_branch's own registration --
this handler does not duplicate those checks. Missing-parameter
validation for the two session ids is likewise left to the downstream
merge_branch() call, which already reports it the same way.

Environment variables (auto_resolve only; same names/semantics as
arbitrate_inference_conflict's, see llm_providers.py):
    CKS_LLM_PROVIDER   -- "auto" (default) | "ollama" | "anthropic".
    ANTHROPIC_API_KEY  -- required only for the "anthropic" provider.
    CKS_LLM_MODEL       -- model override (default: "claude-sonnet-4-6").
    CKS_OLLAMA_MODEL    -- model override for the "ollama" provider
                            (default: llama3.2).
    CKS_OLLAMA_HOST     -- Ollama server URL (default: http://localhost:11434).
    CKS_LLM_MAX_TOKENS  -- optional override (default: 4096).
"""

from __future__ import annotations

import json
import os
from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp import llm_providers
from cks_mcp.errors import internal_error
from cks_mcp.tools.merge.handler import merge_branch

_POLICY = """\
You are resolving a structural merge conflict between two branches of a
knowledge graph that both modified the same object(s) incompatibly. For
each conflicting object, pick 'branch_a' (target), 'branch_b' (source),
or propose a custom synthesized object. Prefer the branch whose edit is
more specific, better-sourced, or carries higher confidence. Respond with
ONLY a JSON object mapping object_id to resolution, e.g.:
{"obj-1": "branch_a", "obj-2": {"identity": {...}, "structure": {...}}}
"""

_SYSTEM_PROMPT = _POLICY


def _default_model() -> str:
    return os.environ.get("CKS_LLM_MODEL", "claude-sonnet-4-6")


def _call_ollama(prompt: str, model: str, max_tokens: int) -> str:
    return llm_providers.call_ollama(
        prompt, system_prompt=_SYSTEM_PROMPT, model=model, max_tokens=max_tokens
    )


def _call_anthropic(prompt: str, model: str, max_tokens: int) -> str:
    return llm_providers.call_anthropic(
        prompt, system_prompt=_SYSTEM_PROMPT, model=model, max_tokens=max_tokens
    )


def _call_llm(prompt: str, *, model: str | None, max_tokens: int) -> str:
    """
    Route the resolution prompt to whichever LLM provider is configured
    or available, mirroring arbitrate_inference_conflict's 'auto' |
    'ollama' | 'anthropic' dispatch (ADR-006) instead of always falling
    through to Anthropic for anything other than an explicit 'ollama'.
    """
    provider = os.environ.get("CKS_LLM_PROVIDER", "auto").lower()

    if provider == "ollama":
        m = model or os.environ.get("CKS_OLLAMA_MODEL", "llama3.2")
        return _call_ollama(prompt, m, max_tokens)

    if provider == "anthropic":
        m = model or _default_model()
        return _call_anthropic(prompt, m, max_tokens)

    if provider != "auto":
        raise RuntimeError(
            f"Unknown CKS_LLM_PROVIDER={provider!r}. Use 'auto', 'ollama', or 'anthropic'."
        )

    if llm_providers.ollama_available():
        m = model or os.environ.get("CKS_OLLAMA_MODEL", "llama3.2")
        return _call_ollama(prompt, m, max_tokens)

    m = model or _default_model()
    return _call_anthropic(prompt, m, max_tokens)


async def resolve_gossip_conflict(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    target_session_id = arguments.get("target_session_id")
    source_session_id = arguments.get("source_session_id")

    # 1. Probe for conflicts
    probe = await merge_branch(runtime, {
        "target_session_id": target_session_id,
        "source_session_id": source_session_id,
    })

    if probe.get("merged"):
        return probe  # no conflict -- already resolved

    conflicts = probe.get("conflicts")
    if not conflicts:
        return probe  # unexpected: merge_branch didn't merge but also reported no conflicts

    # 2. If auto_resolve, call LLM
    if arguments.get("auto_resolve"):
        model = arguments.get("model") or None
        max_tokens = int(arguments.get("max_tokens") or os.environ.get("CKS_LLM_MAX_TOKENS", "4096"))
        prompt = (
            f"Resolve the following merge conflicts:\n\n"
            f"{json.dumps(conflicts, indent=2, ensure_ascii=False)}\n\n"
            "Return a JSON object mapping each object_id to 'branch_a', 'branch_b', or a custom object."
        )
        try:
            raw = _call_llm(prompt, model=model, max_tokens=max_tokens)
            resolutions = json.loads(llm_providers.extract_json(raw))
        except Exception as exc:
            return internal_error(f"LLM resolution failed: {exc}")

        return await merge_branch(runtime, {
            "target_session_id": target_session_id,
            "source_session_id": source_session_id,
            "resolutions": resolutions,
        })

    # 3. Interactive: return conflicts for the caller to resolve
    return {
        "merged": False,
        "conflicts": conflicts,
        "policy": _POLICY,
    }