"""
ResearcherAgent step (ADR-007 Milestone 1): claims objects sitting at
``current_status == "awaiting_research"``, produces a research finding
against the object (an LLM call, same provider-dispatch shape as
``arbitrate_inference_conflict``/``construct_knowledge`` -- see
``cks_mcp.llm_providers``), commits that finding as its own graph node
linked to the object via a ``supports``-semantic edge, appends a
``transition_log`` entry moving the object to
``"awaiting_review"``, and enqueues a ``pipeline_review_request`` task
for the Reviewer step.

Same overall shape as ``cks_mcp.enrichment_agent``: claim via the
generic outbox tools, one atomic ``evolve_knowledge`` call per object
so there is no window where the finding exists unlinked or the status
transition is un-recorded.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.agent_loop import Resolution
from cks_mcp.paths import data_dir
from cks_mcp.pipeline.common import call_llm, find_object
from cks_mcp.pipeline.common import content_hash as compute_content_hash
from cks_mcp.pipeline.schema import (
    PipelineStatus,
    append_transition,
    has_agent_transitioned,
    read_transition_log,
)
from cks_mcp.tools.evolve.handler import evolve_knowledge

AGENT_NAME = "ResearcherAgent"
TASK_TYPE = "pipeline_research_request"
_NEXT_TASK_TYPE = "pipeline_review_request"

_RESEARCHER_SYSTEM_PROMPT = (
    "You are the Researcher agent in a Knowledge Structure pipeline. "
    "Given the name and structure of one object, write a short, "
    "factual research finding relevant to it. Respond with the "
    "finding text only -- no preamble, no markdown."
)


@dataclass(slots=True)
class ResearcherStepSettings:
    """Runtime-tunable knobs for the Researcher step, from env vars."""

    storage_path: str = field(default_factory=lambda: "")
    max_tokens: int = 512

    @classmethod
    def from_env(cls) -> ResearcherStepSettings:
        return cls(
            storage_path=os.environ.get("CKS_MCP_DB_PATH") or str(data_dir() / "cks_mcp.db"),
            max_tokens=int(os.environ.get("CKS_PIPELINE_RESEARCHER_MAX_TOKENS", "512")),
        )


async def resolve_pipeline_research_request(
    runtime: Runtime, task: dict[str, Any], settings: ResearcherStepSettings
) -> Resolution:
    session_id = task["session_id"]
    payload = task.get("payload") or {}
    object_id = payload.get("object_id")
    if not object_id:
        return Resolution(False, "task payload is missing 'object_id'")

    session = runtime.get_session(session_id)
    if session is None:
        return Resolution(False, f"session '{session_id}' not found")

    obj = find_object(session, object_id)
    if obj is None:
        return Resolution(False, f"object '{object_id}' not found in session '{session_id}'")

    content_hash = compute_content_hash(obj)
    current_log = read_transition_log(obj)
    if has_agent_transitioned(obj, AGENT_NAME, content_hash=content_hash):
        # Idempotency guard (ADR-007 Decision 4 / AgentStep.run
        # docstring): already researched this exact content -- nothing
        # to redo, and re-running would just spend another LLM call
        # producing a near-duplicate finding. The next-stage enqueue
        # must still happen on this path: it's what makes a retry
        # after "evolve_knowledge committed but enqueue_task crashed"
        # (or a Reviewer sending the object back with unchanged
        # content) actually resume the pipeline instead of silently
        # completing the task with nothing left in any queue.
        existing_finding_id = next(
            (
                entry.get("reasoning_node_id")
                for entry in reversed(current_log)
                if entry.get("agent") == AGENT_NAME and entry.get("content_hash") == content_hash
            ),
            None,
        )
        await _enqueue_review(runtime, session_id, object_id, existing_finding_id)
        return Resolution(True, PipelineStatus.AWAITING_REVIEW)

    prompt = (
        f"Object name: {obj.identity.name}\n"
        f"Object type: {obj.identity.type}\n"
        f"Structure: {json.dumps(dict(obj.structure or {}), default=str)}\n\n"
        "Write one short research finding relevant to this object."
    )

    try:
        finding_text, model_used = call_llm(
            prompt,
            system_prompt=_RESEARCHER_SYSTEM_PROMPT,
            tool_name="pipeline_researcher_step",
            model=None,
            max_tokens=settings.max_tokens,
        )
    except RuntimeError as exc:
        return Resolution(False, f"LLM call failed: {exc}")

    finding_id = f"research-{object_id}-{content_hash[:12]}"
    ops: list[dict[str, Any]] = [
        {
            "type": "add_object",
            "identity": {
                "id": finding_id,
                "type": "ReasoningNode",
                "name": f"Research finding for {obj.identity.name}",
            },
            "structure": {
                "kind": "research_finding",
                "agent": AGENT_NAME,
                "model": model_used,
                "content": finding_text,
                "object_id": object_id,
            },
        },
        {
            "type": "add_relation",
            "identity": {
                "id": f"rel-supports-{finding_id}-{object_id}",
                "type": "Relation",
                "name": "supports",
            },
            "participants": [finding_id, object_id],
            "relation_type": "depends_on",
            "structure": {"base_type": "depends_on", "semantic_type": "supports"},
        },
        append_transition(
            object_id,
            agent=AGENT_NAME,
            action="researched",
            transitioned_to=PipelineStatus.AWAITING_REVIEW,
            current_log=current_log,
            reasoning_node_id=finding_id,
            content_hash=content_hash,
        ),
    ]

    evolve_result = await evolve_knowledge(runtime, {"session_id": session_id, "operations": ops})
    if evolve_result.get("error"):
        return Resolution(False, f"evolve_knowledge failed: {evolve_result}")

    await _enqueue_review(runtime, session_id, object_id, finding_id)

    return Resolution(True, PipelineStatus.AWAITING_REVIEW)


async def _enqueue_review(
    runtime: Runtime, session_id: str, object_id: str, reasoning_node_id: str | None
) -> None:
    """Enqueue the ``pipeline_review_request`` task that hands ``object_id``
    to the Reviewer step. Called from both the "did fresh work" path and
    the idempotent-skip path above -- see the comment there for why the
    skip path must not be allowed to drop this."""
    await runtime.storage.enqueue_task(
        task_type=_NEXT_TASK_TYPE,
        session_id=session_id,
        payload=json.dumps({"object_id": object_id, "reasoning_node_id": reasoning_node_id}),
    )


class ResearcherStep:
    """``AgentStep`` (ADR-007 Minimal API) wrapping
    ``resolve_pipeline_research_request`` for ``CKSAgentOrchestrator``."""

    name = AGENT_NAME
    claims_status = PipelineStatus.AWAITING_RESEARCH
    task_type = TASK_TYPE

    def __init__(self, settings: ResearcherStepSettings | None = None) -> None:
        self.settings = settings or ResearcherStepSettings.from_env()

    async def run(self, ctx: Any, task: dict[str, Any]) -> Resolution:
        return await resolve_pipeline_research_request(ctx.runtime, task, self.settings)