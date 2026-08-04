"""
Enrichment Agent: an autonomous, unattended process that grows the
knowledge graph from external sources -- the "Enrichment Agent
(external RAG / graph auto-growth)" item from ROADMAP.md.

``search_semantic`` only searches *inside* the graph a session already
has. This module is the other half: given an object that needs more
context (queued via ``request_enrichment``, see that tool's docstring),
it searches *outside* the graph, filters and scores what it finds, and
commits whatever clears the bar back into the session -- linked to the
object that triggered the search, with its own provenance.

Same architecture as ``cks_mcp.critic_agent`` (see that module's
docstring for the full rationale): a separate OS process, its own
``Runtime`` sharing storage with the main server, looping claim ->
resolve -> complete/fail/dead-letter over the persistent outbox via
``cks_mcp.agent_loop``. Reuses the *exact same* four MCP tools Critic
Agent uses for that (``claim_conflict_task``/``complete_conflict_task``/
``fail_conflict_task``/``dead_letter_conflict_task``) against a
different ``task_type`` (``"enrichment_request"``) -- those tools are
already generic over task_type despite the "conflict" in their names.

Resolution pipeline for one ``enrichment_request`` task:

1. **Query**: ``payload.get("query")``, or the target object's
   ``identity.name`` if no explicit query was given.
2. **Search**: ``cks_mcp.enrichment.adapters.build_enrichment_candidates``
   -- Wikipedia + arXiv by default (PubMed is a planned follow-up, not
   implemented yet). One adapter being down doesn't block the others.
3. **Filter**: ``cks_mcp.enrichment.filters`` -- structural low-value
   URL patterns, plus an operator-configured domain/prefix policy.
4. **Score**: ``cks_mcp.enrichment.scoring.score_candidate`` (domain
   authority + query relevance). Only candidates at or above
   ``CKS_ENRICHMENT_MIN_SCORE`` are worth spending an ``ingest_document``
   call on; only the top ``CKS_ENRICHMENT_MAX_INGESTS`` of those are
   actually fetched.
5. **robots.txt**: ``cks_mcp.enrichment.robots.robots_allows`` -- this
   agent fetches URLs it discovered itself, unattended, so it behaves
   like a crawler and respects robots.txt (unlike ``ingest_document``/
   ``verify_source`` called directly on a human- or LLM-named URL).
6. **Ingest + verify + link**: ``ingest_document`` builds the structure,
   ``verify_source`` builds its provenance record, and one
   ``evolve_knowledge`` call commits both plus an ``enriched_by``
   relation from the new Document back to the object that triggered
   the search -- all three as one atomic evolution, so there's no
   window where the new content exists in the session unlinked/
   unverified.

Finding *nothing* relevant (search ran fine, nothing cleared the score
threshold, or everything was blocked by robots.txt) is a successful
resolution, not a failure -- the task described "is there anything
useful out there", and "no" is a real answer to that question, not an
error. Only a `Resolution(False, ...)` retries; see each branch's
comment in ``resolve_enrichment_request`` for which outcomes are which.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import traceback
from dataclasses import dataclass, field
from typing import Any

from cks_runtime.config import RuntimeConfig
from cks_runtime.runtime import Runtime
from cks_runtime_plugins.cks_core import CksCoreAdapter

from cks_mcp.agent_loop import Resolution, run_resolver_with_heartbeat
from cks_mcp.enrichment.adapters import DEFAULT_ADAPTERS, build_enrichment_candidates
from cks_mcp.enrichment.filters import EnrichmentPolicy
from cks_mcp.enrichment.robots import robots_allows
from cks_mcp.enrichment.scoring import score_candidate
from cks_mcp.paths import data_dir
from cks_mcp.tools.claim_conflict_task.handler import claim_conflict_task
from cks_mcp.tools.complete_conflict_task.handler import complete_conflict_task
from cks_mcp.tools.dead_letter_conflict_task.handler import dead_letter_conflict_task
from cks_mcp.tools.evolve.handler import evolve_knowledge
from cks_mcp.tools.fail_conflict_task.handler import fail_conflict_task
from cks_mcp.tools.ingest_document.handler import ingest_document
from cks_mcp.tools.verify_source.handler import verify_source

_DEFAULT_MAX_RETRIES = 5
_DEFAULT_POLL_INTERVAL_SECONDS = 5.0
_DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 60.0
_DEFAULT_MIN_SCORE = 0.5
_DEFAULT_MAX_INGESTS = 2
_DEFAULT_LIMIT_PER_ADAPTER = 3

_TASK_TYPE = "enrichment_request"


@dataclass(slots=True)
class EnrichmentAgentSettings:
    """Runtime-tunable knobs for the Enrichment Agent loop, from env vars."""

    poll_interval: float = _DEFAULT_POLL_INTERVAL_SECONDS
    max_retries: int = _DEFAULT_MAX_RETRIES
    storage_path: str = field(default_factory=lambda: "")
    heartbeat_interval: float = _DEFAULT_HEARTBEAT_INTERVAL_SECONDS
    adapters: tuple[str, ...] = DEFAULT_ADAPTERS
    limit_per_adapter: int = _DEFAULT_LIMIT_PER_ADAPTER
    min_score: float = _DEFAULT_MIN_SCORE
    max_ingests: int = _DEFAULT_MAX_INGESTS

    @classmethod
    def from_env(cls) -> EnrichmentAgentSettings:
        storage_path = os.environ.get("CKS_MCP_DB_PATH") or str(data_dir() / "cks_mcp.db")
        adapters_raw = os.environ.get("CKS_ENRICHMENT_ADAPTERS", "")
        adapters = (
            tuple(a.strip() for a in adapters_raw.split(",") if a.strip())
            if adapters_raw.strip()
            else DEFAULT_ADAPTERS
        )
        return cls(
            poll_interval=float(
                os.environ.get("CKS_ENRICHMENT_POLL_INTERVAL", _DEFAULT_POLL_INTERVAL_SECONDS)
            ),
            max_retries=int(
                os.environ.get("CKS_ENRICHMENT_MAX_RETRIES", _DEFAULT_MAX_RETRIES)
            ),
            storage_path=storage_path,
            heartbeat_interval=float(
                os.environ.get(
                    "CKS_ENRICHMENT_HEARTBEAT_INTERVAL", _DEFAULT_HEARTBEAT_INTERVAL_SECONDS
                )
            ),
            adapters=adapters,
            limit_per_adapter=int(
                os.environ.get("CKS_ENRICHMENT_LIMIT_PER_ADAPTER", _DEFAULT_LIMIT_PER_ADAPTER)
            ),
            min_score=float(os.environ.get("CKS_ENRICHMENT_MIN_SCORE", _DEFAULT_MIN_SCORE)),
            max_ingests=int(os.environ.get("CKS_ENRICHMENT_MAX_INGESTS", _DEFAULT_MAX_INGESTS)),
        )


# ---------------------------------------------------------------------------
# Structure -> evolve_knowledge operations
# ---------------------------------------------------------------------------


def _ops_from_structure(structure_dict: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Convert a serialized ``{"objects": [...]}`` structure (the shape
    both ``ingest_document`` and ``verify_source`` return -- objects
    and relations mixed in one list, CKS-003 canonical form) into a
    list of ``evolve_knowledge`` operation descriptors.

    A relation entry is identified structurally (its ``structure`` has
    both ``participants`` and ``relation_type``), not by naming
    convention (``identity.type == "Relation"``) -- robust either way,
    and ``parse_operations`` needs ``participants``/``relation_type``
    as top-level operation fields, not nested under ``structure`` the
    way the raw serialized form has them.
    """
    ops: list[dict[str, Any]] = []
    for entry in structure_dict.get("objects", []):
        struct = dict(entry.get("structure") or {})
        if "participants" in struct and "relation_type" in struct:
            participants = struct.pop("participants")
            relation_type = struct.pop("relation_type")
            ops.append(
                {
                    "type": "add_relation",
                    "identity": entry["identity"],
                    "participants": participants,
                    "relation_type": relation_type,
                    "structure": struct,
                }
            )
        else:
            ops.append({"type": "add_object", "identity": entry["identity"], "structure": struct})
    return ops


def _find_object_name(session: Any, object_id: str) -> str | None:
    for obj in session.knowledge_structure.objects:
        if obj.identity.id == object_id:
            return obj.identity.name
    return None


# ---------------------------------------------------------------------------
# Resolution policy
# ---------------------------------------------------------------------------


async def resolve_enrichment_request(
    runtime: Runtime, task: dict[str, Any], settings: EnrichmentAgentSettings | None = None
) -> Resolution:
    settings = settings or EnrichmentAgentSettings.from_env()

    payload = task.get("payload")
    if not isinstance(payload, dict):
        return Resolution(False, f"payload was not a JSON object: {payload!r}")

    object_id = payload.get("object_id")
    if not object_id:
        return Resolution(False, "payload missing required 'object_id'")

    session_id = task["session_id"]
    session = runtime.get_session(session_id)
    if session is None:
        return Resolution(False, f"session '{session_id}' not found")

    object_name = _find_object_name(session, object_id)
    if object_name is None:
        # The object this task was queued for is gone (renamed/removed
        # since the task was enqueued) -- nothing sensible to enrich.
        # Not the agent's fault and retrying won't change it: resolved,
        # not failed.
        return Resolution(True, f"object '{object_id}' no longer exists in session -- nothing to enrich")

    query = str(payload.get("query") or object_name or object_id).strip()

    candidates, adapter_errors = await asyncio.to_thread(
        build_enrichment_candidates,
        query,
        adapters=settings.adapters,
        limit_per_adapter=settings.limit_per_adapter,
    )
    if not candidates:
        if adapter_errors:
            # Every adapter failed (e.g. every search API down/unreachable)
            # -- transient, worth a retry, unlike "adapters worked but
            # found nothing".
            return Resolution(False, f"all search adapters failed: {adapter_errors}")
        return Resolution(True, f"no search results for query {query!r}")

    policy = EnrichmentPolicy.from_env()
    filtered = [c for c in candidates if policy.candidate_allowed(c.url)]

    scored = sorted(
        (
            (score_candidate(c.url, title=c.title, query=query, source_adapter=c.source_adapter), c)
            for c in filtered
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    accepted = [(s, c) for s, c in scored if s >= settings.min_score][: settings.max_ingests]

    if not accepted:
        return Resolution(
            True,
            f"no candidate scored >= {settings.min_score} for query {query!r} "
            f"({len(candidates)} found, {len(filtered)} passed policy filters)",
        )

    linked: list[str] = []
    skipped_robots: list[str] = []
    failures: list[str] = []

    for score, candidate in accepted:
        if not await asyncio.to_thread(robots_allows, candidate.url):
            skipped_robots.append(candidate.url)
            continue

        ingest_result = await ingest_document(runtime, {"url": candidate.url})
        if ingest_result.get("error"):
            failures.append(f"{candidate.url}: ingest_document failed: {ingest_result}")
            continue

        ops = _ops_from_structure(ingest_result["knowledge_structure"])
        doc_op = next(
            (
                op
                for op in ops
                if op["type"] == "add_object" and op["structure"].get("url") == candidate.url
            ),
            None,
        )
        if doc_op is None:
            # Shouldn't happen (ingest_document always builds a Document
            # object carrying the fetched url) -- defensive, not a case
            # observed in practice.
            failures.append(f"{candidate.url}: ingest_document result had no Document object")
            continue
        doc_id = doc_op["identity"]["id"]

        verify_result = await verify_source(runtime, {"url": candidate.url, "subject_id": doc_id})
        if not verify_result.get("error"):
            ops.extend(_ops_from_structure(verify_result))
        # A failed verify_source (e.g. unsafe_url on a redirect target)
        # doesn't block linking the content itself -- provenance is
        # best-effort here, not a hard requirement to enrich at all.

        ops.append(
            {
                "type": "add_relation",
                "identity": {
                    "id": f"rel-enrich-{object_id}-{doc_id}",
                    "type": "Relation",
                    "name": "enriched_by",
                },
                "participants": [object_id, doc_id],
                "relation_type": "enriched_by",
                "structure": {"query": query, "score": score, "source_adapter": candidate.source_adapter},
            }
        )

        evolve_result = await evolve_knowledge(runtime, {"session_id": session_id, "operations": ops})
        if evolve_result.get("error"):
            failures.append(f"{candidate.url}: evolve_knowledge failed: {evolve_result}")
            continue

        linked.append(candidate.url)

    if linked:
        detail_parts = [f"linked {len(linked)} source(s): {linked}"]
        if skipped_robots:
            detail_parts.append(f"skipped (robots.txt): {skipped_robots}")
        if failures:
            detail_parts.append(f"failed: {failures}")
        return Resolution(True, "; ".join(detail_parts))

    if failures:
        # At least one accepted candidate genuinely failed to ingest/
        # link (network error, evolve_knowledge rejected it, ...) and
        # nothing else succeeded -- worth a retry.
        return Resolution(False, f"every accepted candidate failed: {failures}")

    # Nothing failed outright, but everything was blocked by robots.txt
    # -- a legitimate policy outcome, not an error.
    return Resolution(True, f"all candidates disallowed by robots.txt: {skipped_robots}")


_RESOLVERS = {_TASK_TYPE: resolve_enrichment_request}


# ---------------------------------------------------------------------------
# Claim -> resolve -> complete/fail/dead-letter, for one task
# ---------------------------------------------------------------------------


async def _process_one(runtime: Runtime, settings: EnrichmentAgentSettings) -> bool | None:
    """Claim and process at most one enrichment_request task. See
    ``cks_mcp.critic_agent._process_one``, this mirrors it exactly."""
    claim_result = await claim_conflict_task(runtime, {"task_type": _TASK_TYPE})
    if not claim_result.get("supported"):
        print(
            "[cks-enrichment-agent] storage backend does not support the "
            "persistent outbox -- configure a SQLite or Postgres CKS_MCP_DB_PATH.",
            file=sys.stderr,
        )
        return None

    task = claim_result.get("task")
    if task is None:
        return None

    task_id = task["task_id"]

    async def _resolver(rt: Runtime, t: dict[str, Any]) -> Resolution:
        return await resolve_enrichment_request(rt, t, settings)

    try:
        resolution, lease_lost = await run_resolver_with_heartbeat(
            runtime, _resolver, task, task_id, settings.heartbeat_interval
        )
    except Exception as exc:  # noqa: BLE001 -- must never crash the loop
        resolution = Resolution(False, f"unexpected exception: {exc}")
        lease_lost = False
        traceback.print_exc(file=sys.stderr)

    if lease_lost:
        print(
            f"[cks-enrichment-agent] lost lease on task_id={task_id} while resolving "
            "(reclaimed by another worker) -- abandoning without completing/failing it",
            file=sys.stderr,
        )
        return True

    if resolution.resolved:
        await complete_conflict_task(runtime, {"task_id": task_id})
        print(
            f"[cks-enrichment-agent] resolved task_id={task_id} "
            f"session_id={task['session_id']}: {resolution.detail}",
            file=sys.stderr,
        )
        return True

    error = resolution.detail or "unknown error"
    next_retry_count = task["retry_count"] + 1
    if next_retry_count >= settings.max_retries:
        await dead_letter_conflict_task(runtime, {"task_id": task_id, "error": error})
        print(
            f"[cks-enrichment-agent] dead-lettered task_id={task_id} "
            f"after {next_retry_count} attempt(s): {error}",
            file=sys.stderr,
        )
    else:
        await fail_conflict_task(
            runtime, {"task_id": task_id, "retry_count": next_retry_count, "error": error}
        )
        print(
            f"[cks-enrichment-agent] retrying task_id={task_id} "
            f"(attempt {next_retry_count}/{settings.max_retries}): {error}",
            file=sys.stderr,
        )
    return True


async def run_once(runtime: Runtime, settings: EnrichmentAgentSettings | None = None) -> int:
    """Drain every currently-eligible enrichment_request task once."""
    settings = settings or EnrichmentAgentSettings.from_env()
    processed = 0
    while await _process_one(runtime, settings):
        processed += 1
    return processed


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def run_enrichment_agent(
    *,
    settings: EnrichmentAgentSettings | None = None,
    max_iterations: int | None = None,
) -> None:
    """See ``cks_mcp.critic_agent.run_critic_agent`` -- identical shape,
    own ``Runtime`` sharing storage with the main server, polling one
    queue (``enrichment_request``) instead of two."""
    settings = settings or EnrichmentAgentSettings.from_env()

    config = RuntimeConfig(storage_path=settings.storage_path)
    runtime = await Runtime.create(core=CksCoreAdapter(), config=config)

    stop = asyncio.Event()

    def _handle_signal(*_: Any) -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except (NotImplementedError, RuntimeError):
            pass

    print(
        f"[cks-enrichment-agent] started (storage_path={settings.storage_path!r}, "
        f"poll_interval={settings.poll_interval}s, max_retries={settings.max_retries}, "
        f"adapters={settings.adapters}, min_score={settings.min_score}, "
        f"max_ingests={settings.max_ingests})",
        file=sys.stderr,
    )

    try:
        iterations = 0
        while not stop.is_set():
            processed = await run_once(runtime, settings)
            if processed == 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=settings.poll_interval)
                except TimeoutError:
                    pass
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
    finally:
        await runtime.aclose()
        print("[cks-enrichment-agent] stopped", file=sys.stderr)


def main_sync() -> None:
    """Console-script entry point (see pyproject.toml's [project.scripts])."""
    asyncio.run(run_enrichment_agent())


if __name__ == "__main__":
    main_sync()