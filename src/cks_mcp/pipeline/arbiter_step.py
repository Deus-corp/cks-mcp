"""
ArbiterAgent step (ADR-007 Milestone 2): the terminal stage of the
Researcher -> Synthesizer -> Reviewer -> Arbiter pipeline.

Unlike the other three steps, Arbiter is not driven off a
``pipeline_*_request`` task this pipeline itself enqueues -- it
consumes ``contradiction_detected`` tasks, the same outbox queue
``cks_runtime.reasoning.contradiction_sweeper.ContradictionSweeper``
already writes to and ``cks_mcp.critic_agent``'s
``resolve_contradiction_conflict`` already drains mechanically (see
that function's docstring: alphabetically-first-relation-id wins, no
LLM). ``ArbiterStep`` is a second, *informed* consumer of the same
queue: given the two (or more) mutually-exclusive relations a
contradiction names, it pulls their participants' provenance via
``query_subgraph``, asks an LLM which one is best supported by source
reliability/recency/confidence, and removes every relation *except*
the LLM's pick -- rather than trusting the mechanical
alphabetical-first heuristic ``resolve_contradiction`` itself applies
when driven without a pre-chosen winner.

Running both ``critic_agent`` and this step against the same
``contradiction_detected`` queue in the same deployment is a
legitimate but unusual choice: whichever consumer's
``claim_conflict_task`` call wins the atomic outbox claim resolves a
given contradiction (the queue is claim-safe -- see
``cks_mcp.orchestrator``'s own docstring), so only one of the two
resolution strategies applies to any single task. This module does
not change ``critic_agent`` or ``ContradictionSweeper``; a deployment
that wants LLM-informed arbitration exclusively should run the
pipeline agent and leave ``contradiction_detected`` out of
``critic_agent``'s resolver map, but that wiring choice is out of
scope here.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.agent_loop import Resolution
from cks_mcp.paths import data_dir
from cks_mcp.pipeline.common import call_llm, find_object
from cks_mcp.pipeline.schema import (
    PipelineStatus,
    append_transition,
    has_agent_transitioned,
    read_transition_log,
)
from cks_mcp.tools.evolve.handler import evolve_knowledge
from cks_mcp.tools.query_subgraph.handler import query_subgraph_tool
from cks_mcp.tools.resolve_contradiction.handler import (
    resolve_contradiction as resolve_contradiction_tool,
)

AGENT_NAME = "ArbiterAgent"
TASK_TYPE = "contradiction_detected"

_ARBITER_SYSTEM_PROMPT = (
    "You are an arbitration engine. Given two or more conflicting "
    "relations and the provenance of the claims they connect, decide "
    "which single relation is best supported based on source "
    "reliability, recency, and confidence. Return ONLY a JSON "
    "decision: a JSON object with 'winner_relation_id' (the relation "
    "id to keep) and 'reason' (a short justification). No prose, no "
    "markdown, no preamble -- JSON only."
)


@dataclass(slots=True)
class ArbiterStepSettings:
    """Runtime-tunable knobs for the Arbiter step, from env vars."""

    storage_path: str = field(default_factory=lambda: "")
    max_tokens: int = 512
    query_depth: int = 1

    @classmethod
    def from_env(cls) -> ArbiterStepSettings:
        return cls(
            storage_path=os.environ.get("CKS_MCP_DB_PATH") or str(data_dir() / "cks_mcp.db"),
            max_tokens=int(os.environ.get("CKS_PIPELINE_ARBITER_MAX_TOKENS", "512")),
            query_depth=int(os.environ.get("CKS_PIPELINE_ARBITER_QUERY_DEPTH", "1")),
        )


def _contradiction_content_hash(location: str, code: str, relation_ids: list[str]) -> str:
    """Hash identifying *this* contradiction instance -- the set of
    relation ids it names, not any single participant's content. Used
    for the idempotency check (ADR-007 Decision 4): re-delivery of the
    same ``contradiction_detected`` task (e.g. a retry after
    ``evolve_knowledge`` committed but the outbox ``complete`` call
    crashed) must not re-run the LLM."""
    payload = {"location": location, "code": code, "relation_ids": sorted(relation_ids)}
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _parse_decision(raw: str, relation_ids: list[str]) -> tuple[str, str]:
    """Parse the LLM's strict-JSON arbitration response. Raises
    ``ValueError`` on anything that isn't the documented shape, or
    whose ``winner_relation_id`` doesn't name one of the relations
    actually in contention -- an LLM hallucinating an unrelated id
    must not be allowed to silently no-op the resolution."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.removeprefix("json")
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"arbitration response was not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict) or "winner_relation_id" not in parsed:
        raise ValueError(
            "arbitration response JSON must be an object with a 'winner_relation_id' key"
        )

    winner_id = parsed["winner_relation_id"]
    if winner_id not in relation_ids:
        raise ValueError(
            f"winner_relation_id {winner_id!r} is not one of the contended "
            f"relation ids {relation_ids!r}"
        )

    reason = parsed.get("reason", "")
    return winner_id, reason


async def resolve_pipeline_arbitration_request(
    runtime: Runtime, task: dict[str, Any], settings: ArbiterStepSettings
) -> Resolution:
    session_id = task["session_id"]
    payload = task.get("payload") or {}
    location = payload.get("location")
    code = payload.get("code", "")
    if not location:
        return Resolution(False, "task payload is missing 'location'")

    session = runtime.get_session(session_id)
    if session is None:
        return Resolution(False, f"session '{session_id}' not found")

    # a) Resolve the contradiction id ('location') to its current set
    # of contended relation ids via the read-only listing path of
    # resolve_contradiction (no contradiction_ids given).
    listing = await resolve_contradiction_tool(runtime, {"session_id": session_id})
    if listing.get("error"):
        return Resolution(False, f"resolve_contradiction listing failed: {listing}")

    contradiction = next(
        (c for c in listing.get("contradictions", []) if c.get("id") == location), None
    )
    if contradiction is None:
        # Already resolved by an earlier attempt (or unrelated
        # concurrent activity) -- nothing left to arbitrate.
        return Resolution(True, PipelineStatus.RESOLVED)

    relation_ids: list[str] = contradiction["relation_ids"]

    relation_objs = [find_object(session, rid) for rid in relation_ids]
    missing_relations = [rid for rid, obj in zip(relation_ids, relation_objs) if obj is None]
    if missing_relations:
        return Resolution(
            False, f"relation(s) not found in session '{session_id}': {missing_relations}"
        )

    valid_relation_objs = [obj for obj in relation_objs if obj is not None]

    participant_ids: list[str] = sorted(
        {pid for obj in valid_relation_objs for pid in getattr(obj, "participants", [])}
    )
    participant_objs = [find_object(session, pid) for pid in participant_ids]
    missing_participants = [
        pid for pid, obj in zip(participant_ids, participant_objs) if obj is None
    ]
    if missing_participants:
        return Resolution(
            False,
            f"relation participant(s) not found in session '{session_id}': "
            f"{missing_participants}",
        )

    valid_participant_objs = [obj for obj in participant_objs if obj is not None]

    content_hash = _contradiction_content_hash(location, code, relation_ids)
    primary_obj = valid_participant_objs[0] if valid_participant_objs else valid_relation_objs[0]

    if has_agent_transitioned(primary_obj, AGENT_NAME, content_hash=content_hash):
        # Idempotency guard: already arbitrated this exact
        # contradiction. Arbiter is the terminal pipeline stage, so
        # unlike Researcher/Synthesizer/Reviewer there is no next-stage
        # task to (re-)enqueue on the skip path -- resolving the
        # contradiction is itself the end state.
        return Resolution(True, PipelineStatus.RESOLVED)

    # b)/c) Load provenance context for the contended claims via
    # query_subgraph, and ask the LLM to arbitrate.
    subgraph = await query_subgraph_tool(
        runtime,
        {
            "session_id": session_id,
            "seed_ids": participant_ids,
            "depth": settings.query_depth,
            "compact_mode": True,
        },
    )
    if subgraph.get("error"):
        return Resolution(False, f"query_subgraph failed: {subgraph}")

    relations_context = [
        {
            "relation_id": obj.identity.id,
            "relation_type": getattr(obj, "relation_type", None),
            "participants": list(getattr(obj, "participants", [])),
        }
        for obj in valid_relation_objs
    ]
    claims_context = subgraph.get("subgraph", {}).get("nodes", [])

    prompt = (
        f"Contradiction code: {code}\n"
        f"Contended relations: {json.dumps(relations_context, default=str)}\n\n"
        f"Claim provenance: {json.dumps(claims_context, default=str)}\n\n"
        "Decide which single relation id should be kept. Respond with JSON only."
    )

    try:
        raw_response, model_used = call_llm(
            prompt,
            system_prompt=_ARBITER_SYSTEM_PROMPT,
            tool_name="pipeline_arbiter_step",
            model=None,
            max_tokens=settings.max_tokens,
        )
    except RuntimeError as exc:
        return Resolution(False, f"LLM call failed: {exc}")

    try:
        winner_relation_id, reason = _parse_decision(raw_response, relation_ids)
    except ValueError as exc:
        return Resolution(False, f"failed to parse arbitration response: {exc}")

    # e) Mechanically apply the LLM's decision: remove every contended
    # relation except the winner. This deliberately does not delegate
    # to resolve_contradiction's own commit path (which always drops
    # the alphabetically-first id) -- see module docstring.
    loser_relation_ids = [rid for rid in relation_ids if rid != winner_relation_id]

    ops: list[dict[str, Any]] = [
        {"type": "remove_relation", "relation_id": rid} for rid in loser_relation_ids
    ]

    verdict_id = f"arbitration-{location}-{content_hash[:12]}"
    ops.append(
        {
            "type": "add_object",
            "identity": {
                "id": verdict_id,
                "type": "ReasoningNode",
                "name": f"Arbitration verdict for {location}",
            },
            "structure": {
                "kind": "arbitration_verdict",
                "agent": AGENT_NAME,
                "model": model_used,
                "code": code,
                "winner_relation_id": winner_relation_id,
                "removed_relation_ids": loser_relation_ids,
                "reason": reason,
            },
        }
    )

    # f) One transition_log entry per contended-claim participant, all
    # referencing the same verdict node.
    for obj in valid_participant_objs:
        ops.append(
            append_transition(
                obj.identity.id,
                agent=AGENT_NAME,
                action="arbitrated",
                transitioned_to=PipelineStatus.RESOLVED,
                current_log=read_transition_log(obj),
                reasoning_node_id=verdict_id,
                content_hash=content_hash,
            )
        )

    evolve_result = await evolve_knowledge(
        runtime,
        {
            "session_id": session_id,
            "operations": ops,
            "extensions": ["mutual_exclusion", "functional_relation"],
        },
    )
    if evolve_result.get("error"):
        return Resolution(False, f"evolve_knowledge failed: {evolve_result}")

    return Resolution(True, PipelineStatus.RESOLVED)


class ArbiterStep:
    """``AgentStep`` (ADR-007 Minimal API) wrapping
    ``resolve_pipeline_arbitration_request`` for ``CKSAgentOrchestrator``."""

    name = AGENT_NAME
    claims_status = PipelineStatus.AWAITING_ARBITRATION
    task_type = TASK_TYPE

    def __init__(self, settings: ArbiterStepSettings | None = None) -> None:
        self.settings = settings or ArbiterStepSettings.from_env()

    async def run(self, ctx: Any, task: dict[str, Any]) -> Resolution:
        return await resolve_pipeline_arbitration_request(ctx.runtime, task, self.settings)
