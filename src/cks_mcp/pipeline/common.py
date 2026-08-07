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
import os
from typing import Any

from cks_mcp import llm_providers

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
    """Same 'auto'/'ollama'/'anthropic' dispatch used throughout
    cks_mcp.tools -- see ``arbitrate_inference_conflict.handler._call_llm``.
    Returns ``(response_text, model_used)``."""
    provider = os.environ.get("CKS_LLM_PROVIDER", "auto").lower()
    default_model = os.environ.get("CKS_LLM_MODEL", "claude-sonnet-4-6")

    if provider == "ollama" or (provider == "auto" and llm_providers.ollama_available()):
        m = model or os.environ.get("CKS_OLLAMA_MODEL", "llama3.2")
        return (
            llm_providers.call_ollama(
                prompt,
                system_prompt=system_prompt,
                model=m,
                max_tokens=max_tokens,
                tool_name=tool_name,
            ),
            m,
        )

    if provider not in ("auto", "anthropic"):
        raise RuntimeError(
            f"Unknown CKS_LLM_PROVIDER={provider!r}. Use 'auto', 'ollama', or 'anthropic'."
        )

    m = model or default_model
    return (
        llm_providers.call_anthropic(
            prompt,
            system_prompt=system_prompt,
            model=m,
            max_tokens=max_tokens,
            tool_name=tool_name,
        ),
        m,
    )