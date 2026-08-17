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
from cks_mcp.session_refresh import reload_session_from_storage

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


async def refresh_session(runtime: Any, session: Any) -> Any:
    """Sync ``session``'s in-memory knowledge_structure with storage
    before a step reads it for its idempotency check.

    Root cause of the ``Outbox task ... failed: Object '...' already
    exists`` failures seen from ``ResearcherStep``/``ReviewerStep``:
    each standalone agent process (``cks_mcp.pipeline_agent`` et al.,
    see ``cks_mcp.session_refresh``'s module docstring) keeps its own
    in-memory session cache that ``Runtime.get_session`` never
    refreshes on its own. A step that reads a stale copy of
    ``transition_log`` can conclude (wrongly) that it hasn't already
    researched/reviewed this object, redo the LLM call, and then hit
    ``evolve_knowledge``'s ``add_object`` for its deterministic node id
    -- which some other process (or an earlier, crashed run of this
    same task) already committed. Reloading right before the
    idempotency check closes the common (non-racing) version of this
    gap; ``is_duplicate_object_error`` below is the second half, for
    the case where two writers still race past the reload.

    Best-effort, same contract as ``reload_session_from_storage``
    itself: a storage backend or test double that can't be reloaded
    (no ``session_id``, no persisted record yet, an in-memory-only
    fixture, ...) is left untouched rather than raising -- a step
    whose session simply isn't reloadable should still run against
    whatever ``get_session`` handed it, not fail the task outright.
    """
    try:
        return await reload_session_from_storage(runtime, session)
    except Exception:  # noqa: BLE001
        return session


def is_duplicate_object_error(evolve_result: dict[str, Any], object_id: str) -> bool:
    """Did ``evolve_knowledge`` fail because ``object_id`` -- a
    pipeline step's own deterministic (content-hash-derived) node id
    -- already exists in the session?

    This is the failure mode left over even after ``refresh_session``:
    two writers (e.g. two ``cks_mcp.pipeline_agent`` processes, or a
    retried outbox task racing the run that already completed it) both
    pass the pre-``evolve_knowledge`` idempotency check on a stale-but
    equally-fresh read, then both attempt to ``add_object`` the same
    id. One wins; ``evolve_knowledge`` for the other returns an
    ``Evolution failed`` error whose message names that id -- not the
    retryable ``concurrent_modification`` error, since by the time the
    loser's commit is retried the *reload* succeeds but the *dry-run
    re-check* now fails on a genuine duplicate id rather than a stale
    version. Callers use this to distinguish "I lost a race, my work
    is already done" (fold into a no-op success) from every other
    ``evolve_knowledge`` failure (a real error to surface).
    """
    if not evolve_result.get("error"):
        return False
    message = str(evolve_result.get("error") or evolve_result.get("message") or "")
    return "already exists" in message and object_id in message


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