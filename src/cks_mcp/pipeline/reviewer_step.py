"""
ReviewerAgent step (ADR-007 Milestone 1) -- the role named "Critic" in
early planning notes, renamed to avoid colliding with
``cks_mcp.critic_agent`` (the gossip/inference/provenance/contradiction
conflict resolver, an unrelated agent that predates this pipeline).

Claims objects at ``current_status == "awaiting_review"``, reads the
object plus its linked Researcher finding via ``query_subgraph``,
produces a verdict (an LLM call), writes that verdict as its own
``ReasoningNode``/``CritiqueNode`` linked in via a ``supports``/
``refutes`` semantic edge (ADR-007 Decision 4 -- never inlined into
the ``transition_log`` entry itself), and appends a transition moving
the object to ``"resolved"`` on approval or back to
``"needs_research"`` (with the rejection reasoning attached) on
rejection.

Idempotency (ADR-007 Decision 4 / the ``AgentStep.run`` docstring):
before calling the LLM, checks ``transition_log`` for an existing
``ReviewerAgent`` entry against the object's current content hash and
skips straight to reporting that prior outcome if found.
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

AGENT_NAME = "ReviewerAgent"
TASK_TYPE = "pipeline_review_request"
_RESEARCH_TASK_TYPE = "pipeline_research_request"

_REVIEWER_SYSTEM_PROMPT = (
    "You are the Reviewer agent in a Knowledge Structure pipeline. "
    "Given an object, its structure, and a research finding about it, "
    "decide whether the finding is well-supported and relevant. "
    "Respond with exactly one line: 'APPROVE: <one-sentence reason>' "
    "or 'REJECT: <one-sentence reason>'."
)


@dataclass(slots=True)
class ReviewerStepSettings:
    """Runtime-tunable knobs for the Reviewer step, from env vars."""

    storage_path: str = field(default_factory=lambda: "")
    max_tokens: int = 256

    @classmethod
    def from_env(cls) -> ReviewerStepSettings:
        return cls(
            storage_path=os.environ.get("CKS_MCP_DB_PATH") or str(data_dir() / "cks_mcp.db"),
            max_tokens=int(os.environ.get("CKS_PIPELINE_REVIEWER_MAX_TOKENS", "256")),
        )


def _parse_verdict(raw: str) -> tuple[bool, str]:
    text = raw.strip()
    if text.upper().startswith("APPROVE"):
        return True, text.split(":", 1)[1].strip() if ":" in text else text
    if text.upper().startswith("REJECT"):
        return False, text.split(":", 1)[1].strip() if ":" in text else text
    # Model didn't follow the format -- treat as a non-committal
    # rejection rather than silently approving unparseable output.
    return False, f"unparseable verdict, treated as reject: {text[:200]}"


async def resolve_pipeline_review_request(
    runtime: Runtime, task: dict[str, Any], settings: ReviewerStepSettings
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
        # Idempotency guard, same rationale as researcher_step's: this
        # path is what runs on a retry (e.g. evolve_knowledge committed
        # last time but the process died before this function
        # returned). It must still push the object to wherever its
        # last recorded verdict says it belongs -- otherwise a retried
        # rejection permanently strands the object with no task in any
        # queue (see _route_next_stage).
        for entry in reversed(current_log):
            if entry.get("agent") == AGENT_NAME and entry.get("content_hash") == content_hash:
                prior_status = entry.get("transitioned_to", PipelineStatus.RESOLVED)
                await _route_next_stage(runtime, session_id, object_id, prior_status)
                return Resolution(True, prior_status)
        return Resolution(True, PipelineStatus.RESOLVED)

    finding_node_id = payload.get("reasoning_node_id")
    finding = find_object(session, finding_node_id) if finding_node_id else None
    finding_text = (finding.structure or {}).get("content", "") if finding is not None else ""

    prompt = (
        f"Object name: {obj.identity.name}\n"
        f"Object type: {obj.identity.type}\n"
        f"Structure: {json.dumps(dict(obj.structure or {}), default=str)}\n\n"
        f"Research finding: {finding_text or '(none available)'}\n\n"
        "Approve or reject this finding for the object."
    )

    try:
        raw_verdict, model_used = call_llm(
            prompt,
            system_prompt=_REVIEWER_SYSTEM_PROMPT,
            tool_name="pipeline_reviewer_step",
            model=None,
            max_tokens=settings.max_tokens,
        )
    except RuntimeError as exc:
        return Resolution(False, f"LLM call failed: {exc}")

    approved, reason = _parse_verdict(raw_verdict)
    verdict_id = f"review-{object_id}-{content_hash[:12]}"
    semantic_type = "supports" if approved else "refutes"
    new_status = PipelineStatus.RESOLVED if approved else PipelineStatus.NEEDS_RESEARCH

    ops: list[dict[str, Any]] = [
        {
            "type": "add_object",
            "identity": {
                "id": verdict_id,
                "type": "ReasoningNode",
                "name": f"Review verdict for {obj.identity.name}",
            },
            "structure": {
                "kind": "review_verdict",
                "agent": AGENT_NAME,
                "model": model_used,
                "approved": approved,
                "reason": reason,
                "object_id": object_id,
            },
        },
        {
            "type": "add_relation",
            "identity": {
                "id": f"rel-{semantic_type}-{verdict_id}-{object_id}",
                "type": "Relation",
                "name": semantic_type,
            },
            "participants": [verdict_id, object_id],
            "relation_type": "depends_on",
            "structure": {"base_type": "depends_on", "semantic_type": semantic_type},
        },
        append_transition(
            object_id,
            agent=AGENT_NAME,
            action="reviewed",
            transitioned_to=new_status,
            current_log=current_log,
            reasoning_node_id=verdict_id,
            content_hash=content_hash,
        ),
    ]

    evolve_result = await evolve_knowledge(runtime, {"session_id": session_id, "operations": ops})
    if evolve_result.get("error"):
        return Resolution(False, f"evolve_knowledge failed: {evolve_result}")

    await _route_next_stage(runtime, session_id, object_id, new_status)

    return Resolution(True, new_status)


async def _route_next_stage(
    runtime: Runtime, session_id: str, object_id: str, new_status: str
) -> None:
    """Put ``object_id`` back on a queue matching its post-review status.

    ``RESOLVED`` has no Milestone-1 next step (Synthesizer/Arbiter are
    Milestone 2) so nothing is enqueued. ``NEEDS_RESEARCH`` must be
    re-enqueued onto the Researcher's own queue -- without this call an
    object rejected by the Reviewer changes ``current_status`` but has
    no outbox task anywhere, so ``ResearcherStep`` (which only ever
    claims from its ``task_type`` queue, never scans by status) never
    sees it again."""
    if new_status == PipelineStatus.NEEDS_RESEARCH:
        await runtime.storage.enqueue_task(
            task_type=_RESEARCH_TASK_TYPE,
            session_id=session_id,
            payload=json.dumps({"object_id": object_id}),
        )


class ReviewerStep:
    """``AgentStep`` (ADR-007 Minimal API) wrapping
    ``resolve_pipeline_review_request`` for ``CKSAgentOrchestrator``."""

    name = AGENT_NAME
    claims_status = PipelineStatus.AWAITING_REVIEW
    task_type = TASK_TYPE

    def __init__(self, settings: ReviewerStepSettings | None = None) -> None:
        self.settings = settings or ReviewerStepSettings.from_env()

    async def run(self, ctx: Any, task: dict[str, Any]) -> Resolution:
        return await resolve_pipeline_review_request(ctx.runtime, task, self.settings)