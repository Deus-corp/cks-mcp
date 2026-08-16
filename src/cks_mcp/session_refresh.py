"""
Shared helper: refresh an in-memory ``RuntimeSession`` in place from
persisted storage.

Root-cause context (see ``middleware.refresh_session_from_storage`` and
the Run History "stuck on Queued" investigation): ``Runtime.get_session``
only ever returns a process-local in-memory cache
(``SessionManager``'s dict, populated once at startup via
``Runtime._restore_from_storage`` and otherwise never refreshed on its
own). Several standalone agent processes -- ``cks-pipeline-agent``
(``cks_mcp.pipeline_agent``), the Critic/Enrichment agents, etc. -- run
in their *own* OS process with their *own* ``Runtime``/in-memory
session cache, sharing only the on-disk SQLite/Postgres backend with
the main cks-mcp server that services cks-studio's tool calls. A
mutation committed by one of those agents (via ``evolve_knowledge`` in
*their* process) is durably persisted, but the main server's
in-memory copy of that session has no way to find out about it until
something explicitly reloads it from storage -- so reads like
``list_pipeline_runs``, ``query_subgraph``, ``serialize_knowledge``
kept observing a stale snapshot indefinitely (a run's
``transition_log`` entries the pipeline agent had already written
were invisible to ``list_pipeline_runs`` running in the main server
process, so a run appeared permanently "Queued" even while the agent
was actively completing steps).

This function was previously private to
``cks_mcp.tools.evolve.handler`` (used only on its own commit-retry
path); it's shared here so ``middleware.refresh_session_from_storage``
can apply the same reload to every session-scoped tool call, not just
``evolve_knowledge``'s own retries.
"""

from __future__ import annotations

from cks_runtime.runtime import Runtime
from cks_runtime.session.session import RuntimeSession


async def reload_session_from_storage(
    runtime: Runtime, session: RuntimeSession
) -> RuntimeSession:
    """Refresh ``session`` in place from the persisted record, if any.

    Mutates ``session`` in place (rather than returning a new object)
    so every existing reference to it -- including the one
    ``Runtime.get_session``/``SessionManager`` itself holds -- observes
    the refreshed state, matching ``SessionManager.restore``'s "same
    identity, fresher content" contract used at startup. A session
    that no longer exists in storage (e.g. was never persisted, as
    with in-memory-only test sessions) is left untouched -- this is a
    best-effort freshen, not a source of truth for existence.
    """
    fresh = await runtime.storage.load_session(session.session_id)
    if fresh is not None:
        session.knowledge_structure = fresh.knowledge_structure
        session.version_history = fresh.version_history
        session.metadata = fresh.metadata
        session.closed = fresh.closed
    return session
