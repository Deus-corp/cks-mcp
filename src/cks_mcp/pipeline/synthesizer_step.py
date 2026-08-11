"""
SynthesizerAgent step (ADR-007 Milestone 2): claims a set of objects
sitting at ``current_status == "awaiting_synthesis"`` (a
``pipeline_synthesis_request`` task carrying ``object_ids``), pulls
their raw content via ``query_subgraph``, asks an LLM to deduplicate
and reconcile them into a single synthesized ``KnowledgeStructure``
fragment (contradictions become their own ``Claim`` nodes rather than
being silently dropped), commits that fragment plus one
``transition_log`` entry per source object via a single atomic
``evolve_knowledge`` call, and enqueues a ``pipeline_review_request``
task so the synthesized node flows into the existing Reviewer step
(ADR-007 Milestone 1) -- Synthesizer produces new candidate knowledge,
it does not itself decide whether that knowledge is good.

Same overall shape as ``researcher_step``/``reviewer_step``: claim via
the generic outbox tools, one atomic ``evolve_knowledge`` call so
there is no window where the synthesized node exists unlinked or the
source objects' status transitions are un-recorded.
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

AGENT_NAME = "SynthesizerAgent"
TASK_TYPE = "pipeline_synthesis_request"
_NEXT_TASK_TYPE = "pipeline_review_request"

_SYNTHESIZER_SYSTEM_PROMPT = (
    "You are a knowledge synthesis engine. Given a set of raw facts "
    "extracted from a Knowledge Structure, deduplicate them and "
    "reconcile any contradictions by expressing each contradiction as "
    "its own Claim node (never silently drop or overwrite a "
    "conflicting fact). Output ONLY valid CKS JSON describing the "
    "synthesized objects: a JSON object with a single key "
    "'objects', a list of {\"id\", \"type\", \"name\", \"structure\"} "
    "entries. No prose, no markdown, no preamble -- JSON only."
)


@dataclass(slots=True)
class SynthesizerStepSettings:
    """Runtime-tunable knobs for the Synthesizer step, from env vars."""

    storage_path: str = field(default_factory=lambda: "")
    max_tokens: int = 1024
    query_depth: int = 1

    @classmethod
    def from_env(cls) -> SynthesizerStepSettings:
        return cls(
            storage_path=os.environ.get("CKS_MCP_DB_PATH") or str(data_dir() / "cks_mcp.db"),
            max_tokens=int(os.environ.get("CKS_PIPELINE_SYNTHESIZER_MAX_TOKENS", "1024")),
            query_depth=int(os.environ.get("CKS_PIPELINE_SYNTHESIZER_QUERY_DEPTH", "1")),
        )


def _objects_content_hash(objects: list[Any]) -> str:
    """Hash of the combined *content* of every source object, excluding
    pipeline bookkeeping fields -- same rationale as
    ``pipeline.common.content_hash``, generalized over a set of
    objects instead of one, so re-running Synthesizer against an
    unchanged set of sources is a no-op (ADR-007 Decision 4)."""
    payload = []
    for obj in sorted(objects, key=lambda o: o.identity.id):
        structure = dict(obj.structure or {})
        structure.pop("current_status", None)
        structure.pop("transition_log", None)
        payload.append({"id": obj.identity.id, "structure": structure})
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _parse_synthesis_response(raw: str) -> list[dict[str, Any]]:
    """Parse the LLM's strict-JSON synthesis response into a list of
    object descriptors. Raises ``ValueError`` on anything that isn't
    the documented shape -- callers turn that into a failed
    ``Resolution`` rather than committing malformed data."""
    text = raw.strip()
    if text.startswith("```"):
        # Strip an accidental markdown fence even though the system
        # prompt forbids it -- models drift on this often enough that
        # failing hard here would make the step needlessly brittle.
        text = text.strip("`")
        text = text.removeprefix("json")
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"synthesis response was not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict) or "objects" not in parsed:
        raise ValueError("synthesis response JSON must be an object with an 'objects' key")

    objects = parsed["objects"]
    if not isinstance(objects, list) or not objects:
        raise ValueError("synthesis response 'objects' must be a non-empty list")

    for entry in objects:
        if not isinstance(entry, dict) or "id" not in entry:
            raise ValueError("each synthesized object needs at least an 'id'")

    return objects


async def resolve_pipeline_synthesis_request(
    runtime: Runtime, task: dict[str, Any], settings: SynthesizerStepSettings
) -> Resolution:
    session_id = task["session_id"]
    payload = task.get("payload") or {}
    object_ids = payload.get("object_ids")
    if not object_ids:
        return Resolution(False, "task payload is missing 'object_ids'")

    session = runtime.get_session(session_id)
    if session is None:
        return Resolution(False, f"session '{session_id}' not found")

    objs = [find_object(session, oid) for oid in object_ids]
    missing = [oid for oid, obj in zip(object_ids, objs) if obj is None]
    if missing:
        return Resolution(False, f"object(s) not found in session '{session_id}': {missing}")

    content_hash = _objects_content_hash(objs)
    primary_object = objs[0]
    current_log = read_transition_log(primary_object)

    if has_agent_transitioned(primary_object, AGENT_NAME, content_hash=content_hash):
        # Idempotency guard (ADR-007 Decision 4 / AgentStep.run
        # docstring): already synthesized this exact set of source
        # contents -- skip the LLM call, but still make sure the
        # synthesized node is (re-)enqueued for review, same rationale
        # as researcher_step's idempotent-skip path.
        existing_synth_id = next(
            (
                entry.get("reasoning_node_id")
                for entry in reversed(current_log)
                if entry.get("agent") == AGENT_NAME and entry.get("content_hash") == content_hash
            ),
            None,
        )
        await _enqueue_review(runtime, session_id, existing_synth_id, object_ids)
        return Resolution(True, PipelineStatus.AWAITING_REVIEW)

    # a) Load raw facts via query_subgraph.
    subgraph = await query_subgraph_tool(
        runtime,
        {"session_id": session_id, "seed_ids": object_ids, "depth": settings.query_depth},
    )
    if subgraph.get("error"):
        return Resolution(False, f"query_subgraph failed: {subgraph}")

    raw_facts = [
        {
            "id": obj.identity.id,
            "type": obj.identity.type,
            "name": obj.identity.name,
            "structure": {
                k: v
                for k, v in dict(obj.structure or {}).items()
                if k not in ("current_status", "transition_log")
            },
        }
        for obj in objs
    ]

    prompt = (
        "Raw facts:\n"
        f"{json.dumps(raw_facts, default=str)}\n\n"
        "Deduplicate these facts and resolve any contradictions as "
        "Claim nodes. Respond with JSON only."
    )

    try:
        raw_response, model_used = call_llm(
            prompt,
            system_prompt=_SYNTHESIZER_SYSTEM_PROMPT,
            tool_name="pipeline_synthesizer_step",
            model=None,
            max_tokens=settings.max_tokens,
        )
    except RuntimeError as exc:
        return Resolution(False, f"LLM call failed: {exc}")

    try:
        synthesized_objects = _parse_synthesis_response(raw_response)
    except ValueError as exc:
        return Resolution(False, f"failed to parse synthesis response: {exc}")

    synth_id = f"synthesis-{'-'.join(object_ids)[:60]}-{content_hash[:12]}"

    ops: list[dict[str, Any]] = []
    for entry in synthesized_objects:
        node_id = f"{synth_id}-{entry['id']}"
        ops.append(
            {
                "type": "add_object",
                "identity": {
                    "id": node_id,
                    "type": entry.get("type", "Claim"),
                    "name": entry.get("name", f"Synthesized: {entry['id']}"),
                },
                "structure": {
                    **entry.get("structure", {}),
                    "kind": "synthesized_fact",
                    "agent": AGENT_NAME,
                    "model": model_used,
                    "source_object_ids": object_ids,
                },
            }
        )
        for source_id in object_ids:
            ops.append(
                {
                    "type": "add_relation",
                    "identity": {
                        "id": f"rel-synthesizes-{node_id}-{source_id}",
                        "type": "Relation",
                        "name": "synthesizes",
                    },
                    "participants": [node_id, source_id],
                    "relation_type": "depends_on",
                    "structure": {"base_type": "depends_on", "semantic_type": "synthesizes"},
                }
            )

    # f) One transition_log entry per source object, all referencing
    # the same synth_id "group" so idempotency/lookup works uniformly
    # regardless of which source object a later retry inspects first.
    for oid, obj in zip(object_ids, objs):
        ops.append(
            append_transition(
                oid,
                agent=AGENT_NAME,
                action="synthesized",
                transitioned_to=PipelineStatus.AWAITING_REVIEW,
                current_log=read_transition_log(obj),
                reasoning_node_id=synth_id,
                content_hash=content_hash,
            )
        )

    evolve_result = await evolve_knowledge(runtime, {"session_id": session_id, "operations": ops})
    if evolve_result.get("error"):
        return Resolution(False, f"evolve_knowledge failed: {evolve_result}")

    await _enqueue_review(runtime, session_id, synth_id, object_ids)

    return Resolution(True, PipelineStatus.AWAITING_REVIEW)


async def _enqueue_review(
    runtime: Runtime, session_id: str, synth_id: str | None, object_ids: list[str]
) -> None:
    """Enqueue the ``pipeline_review_request`` task handing the
    synthesized node to the existing Reviewer step. Called from both
    the "did fresh work" path and the idempotent-skip path above --
    see the comment there for why the skip path must not drop this."""
    await runtime.storage.enqueue_task(
        task_type=_NEXT_TASK_TYPE,
        session_id=session_id,
        payload=json.dumps(
            {
                "object_id": synth_id,
                "reasoning_node_id": synth_id,
                "source_object_ids": object_ids,
            }
        ),
    )


class SynthesizerStep:
    """``AgentStep`` (ADR-007 Minimal API) wrapping
    ``resolve_pipeline_synthesis_request`` for ``CKSAgentOrchestrator``."""

    name = AGENT_NAME
    claims_status = PipelineStatus.AWAITING_SYNTHESIS
    task_type = TASK_TYPE

    def __init__(self, settings: SynthesizerStepSettings | None = None) -> None:
        self.settings = settings or SynthesizerStepSettings.from_env()

    async def run(self, ctx: Any, task: dict[str, Any]) -> Resolution:
        return await resolve_pipeline_synthesis_request(ctx.runtime, task, self.settings)
