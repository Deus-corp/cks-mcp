"""
Shared helpers for ADR-007 pipeline steps (Researcher, Reviewer, and any
future Synthesizer/Arbiter step).

Factored out once a second step (Reviewer) needed byte-for-byte the same
``_find_object``/``_content_hash``/LLM-provider-dispatch logic Researcher
already had -- same rationale as ``cks_mcp.storage.patch_codec`` gives
for living in its own module: two independently-maintained copies of
this logic are two independent places for behaviour (e.g. which
structure fields get excluded from the content hash, or which
providers/env vars are supported) to silently drift apart between
steps.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from cks_mcp.llm.client import LLMClient, LLMProviderUnavailable
from cks_mcp.llm_providers import (
    call_anthropic,
    call_ollama,
    call_openai_compatible_single_shot,
    ollama_available,
)

# Structure fields every step's idempotency hash excludes -- these are
# the pipeline's own bookkeeping (see pipeline.schema's module
# docstring) and change on every transition a step itself writes, so
# including them would make the hash a moving target and defeat the
# idempotency check it exists for.
_HASH_EXCLUDED_FIELDS = ("current_status", "transition_log")


def find_object(session: Any, object_id: str) -> Any | None:
    """Look up one object by id in a session's live knowledge structure.

    ``KnowledgeStructure`` already keeps an id -> object index for
    exactly this (see ``cks.core.KnowledgeStructure.get``, O(1)); use
    it when available instead of a linear scan over ``.objects``; the
    O(n) scan is a fallback only for stand-ins that don't implement
    ``get`` (e.g. hand-rolled ``SimpleNamespace`` fixtures in tests).
    """
    structure = session.knowledge_structure
    get = getattr(structure, "get", None)
    if callable(get):
        return get(object_id)
    for obj in structure.objects:
        if obj.identity.id == object_id:
            return obj
    return None


def content_hash(obj: Any) -> str:
    """Hash of an object's *content*, excluding pipeline bookkeeping
    fields (see ``_HASH_EXCLUDED_FIELDS``)."""
    structure = dict(obj.structure or {})
    for field in _HASH_EXCLUDED_FIELDS:
        structure.pop(field, None)
    payload = json.dumps(structure, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def call_llm(
    prompt: str,
    *,
    system_prompt: str,
    tool_name: str,
    model: str | None,
    max_tokens: int,
) -> tuple[str, str]:
    """Provider dispatch for pipeline steps -- routes through the same
    ``LLMClient`` (``cks_mcp.llm.client``) ``construct_knowledge`` and
    ``ai_chat`` already use, so ``CKS_LLM_PROVIDER=auto|ollama|anthropic|
    openai_compatible`` behaves identically everywhere in cks-mcp
    instead of pipeline steps maintaining their own, easily-drifting
    copy of the same routing logic (this previously hand-rolled
    'ollama'/'anthropic'/'auto'-only dispatch was exactly that: it never
    got updated when 'openai_compatible' was added elsewhere, so an
    explicit ``CKS_LLM_PROVIDER=openai_compatible`` would raise
    "Unknown CKS_LLM_PROVIDER" here even though ``get_llm_status`` and
    ``construct_knowledge`` both recognized it fine).

    Returns ``(response_text, model_used)``. Raises ``RuntimeError`` on
    any failure -- including ``LLMProviderUnavailable`` (no provider
    configured/reachable at all), which callers here don't need to
    distinguish from any other provider failure; every existing caller
    already just catches ``RuntimeError`` and turns it into a failed
    ``Resolution``.
    """
    client = LLMClient(
        # Built fresh per call (not module-level) so it always picks up
        # the current provider functions -- including ones a test has
        # patched onto this module by name, same convention
        # cks_mcp.tools.ai_chat.handler uses.
        single_shot_ollama_fn=call_ollama,
        single_shot_anthropic_fn=call_anthropic,
        single_shot_openai_compatible_fn=call_openai_compatible_single_shot,
        ollama_available_fn=ollama_available,
    )
    try:
        return client.call_single_shot(
            prompt,
            system_prompt=system_prompt,
            model=model,
            max_tokens=max_tokens,
            tool_name=tool_name,
        )
    except LLMProviderUnavailable as exc:
        raise RuntimeError(str(exc)) from exc