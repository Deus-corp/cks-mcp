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

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp import llm_providers
from cks_mcp.agent_loop import Resolution
from cks_mcp.paths import data_dir
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


def _find_object(session: Any, object_id: str) -> Any | None:
    for obj in session.knowledge_structure.objects:
        if obj.identity.id == object_id:
            return obj
    return None


def _content_hash(obj: Any) -> str:
    """Hash of an object's *content*, excluding the pipeline's own
    bookkeeping fields (``current_status``/``transition_log``) -- those
    change on every transition this very function's caller writes, so
    including them would make the hash a moving target and defeat the
    idempotency check it exists for."""
    structure = dict(obj.structure or {})
    structure.pop("current_status", None)
    structure.pop("transition_log", None)
    payload = json.dumps(structure, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _call_llm(prompt: str, *, model: str | None, max_tokens: int) -> tuple[str, str]:
    """Same 'auto'/'ollama'/'anthropic' dispatch used throughout
    cks_mcp.tools -- see arbitrate_inference_conflict.handler._call_llm."""
    provider = os.environ.get("CKS_LLM_PROVIDER", "auto").lower()
    default_model = os.environ.get("CKS_LLM_MODEL", "claude-sonnet-4-6")

    if provider == "ollama" or (provider == "auto" and llm_providers.ollama_available()):
        m = model or os.environ.get("CKS_OLLAMA_MODEL", "llama3.2")
        return (
            llm_providers.call_ollama(
                prompt,
                system_prompt=_RESEARCHER_SYSTEM_PROMPT,
                model=m,
                max_tokens=max_tokens,
                tool_name="pipeline_researcher_step",
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
            system_prompt=_RESEARCHER_SYSTEM_PROMPT,
            model=m,
            max_tokens=max_tokens,
            tool_name="pipeline_researcher_step",
        ),
        m,
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

    obj = _find_object(session, object_id)
    if obj is None:
        return Resolution(False, f"object '{object_id}' not found in session '{session_id}'")

    content_hash = _content_hash(obj)
    current_log = read_transition_log(obj)
    if has_agent_transitioned(obj, AGENT_NAME, content_hash=content_hash):
        # Idempotency guard (ADR-007 Decision 4 / AgentStep.run
        # docstring): already researched this exact content -- nothing
        # to redo, and re-running would just spend another LLM call
        # producing a near-duplicate finding.
        return Resolution(True, PipelineStatus.AWAITING_REVIEW)

    prompt = (
        f"Object name: {obj.identity.name}\n"
        f"Object type: {obj.identity.type}\n"
        f"Structure: {json.dumps(dict(obj.structure or {}), default=str)}\n\n"
        "Write one short research finding relevant to this object."
    )

    try:
        finding_text, model_used = _call_llm(prompt, model=None, max_tokens=settings.max_tokens)
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

    await runtime.storage.enqueue_task(
        task_type=_NEXT_TASK_TYPE,
        session_id=session_id,
        payload=json.dumps({"object_id": object_id, "reasoning_node_id": finding_id}),
    )

    return Resolution(True, PipelineStatus.AWAITING_REVIEW)


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