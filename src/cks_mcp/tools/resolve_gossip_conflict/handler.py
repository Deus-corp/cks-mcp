"""
resolve_gossip_conflict: LLM-assisted resolution of structural gossip
merge conflicts -- the counterpart to arbitrate_inference_conflict for
gossip conflicts, closing the asymmetry where gossip conflicts required
hand-rolled resolutions while inference conflicts had LLM assistance.
"""

from __future__ import annotations

import json
import os
from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp import llm_providers
from cks_mcp.errors import internal_error, missing_parameter, session_not_found
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


def _call_llm(prompt: str, *, model: str | None, max_tokens: int) -> str:
    provider = os.environ.get("CKS_LLM_PROVIDER", "auto").lower()
    if provider == "ollama":
        m = model or os.environ.get("CKS_OLLAMA_MODEL", "llama3.2")
        return llm_providers.call_ollama(prompt, system_prompt=_SYSTEM_PROMPT, model=m, max_tokens=max_tokens)
    m = model or os.environ.get("CKS_LLM_MODEL", "claude-sonnet-4-6")
    return llm_providers.call_anthropic(prompt, system_prompt=_SYSTEM_PROMPT, model=m, max_tokens=max_tokens)


async def resolve_gossip_conflict(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    target_session_id = arguments.get("target_session_id")
    source_session_id = arguments.get("source_session_id")

    if not target_session_id:
        return missing_parameter("target_session_id")
    if not source_session_id:
        return missing_parameter("source_session_id")

    if runtime.get_session(target_session_id) is None:
        return session_not_found(target_session_id)
    if runtime.get_session(source_session_id) is None:
        return session_not_found(source_session_id)

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