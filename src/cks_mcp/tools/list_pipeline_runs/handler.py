"""
list_pipeline_runs: read-only reconstruction of ADR-007 pipeline runs
(Researcher -> Synthesizer -> Reviewer -> Arbiter) for a session, for
cks-studio's Run History panel.

Deliberately does not introduce a new storage table or outbox record
for "a run" as its own row (see the task description this was
implemented against). Instead it derives everything from data that
already exists:

- Each ``start_pipeline`` call now stamps its ``pipeline_run_hash`` as
  ``run_id`` onto the outbox payload it enqueues, and
  ``ResearcherStep``/``ReviewerStep`` both thread that same ``run_id``
  through to the ``transition_log`` entries they append (see
  ``cks_mcp.pipeline.schema.append_transition``) and to whatever
  next-stage task they enqueue. Grouping every object's transition_log
  entries by ``run_id`` reconstructs "which objects did this run touch,
  and what did each pipeline step do to them".
- Objects that haven't been claimed by a step yet have no transition
  entry at all; those are recovered from ``list_tasks_by_type``'s
  PENDING peek (``drain=False`` -- this tool must never consume a task
  another worker still needs to claim) over the two Milestone-1 task
  types this pipeline currently enqueues
  (``pipeline_research_request``/``pipeline_review_request``).
- A step that failed and was dead-lettered is recovered the same way,
  via ``list_dead_letter_tasks``.

A run whose every object predates the ``run_id`` field, or whose
objects have since been deleted from the session, simply cannot be
reconstructed and will not appear -- documented in the task as an
acceptable Phase-1 limitation.
"""

from __future__ import annotations

import json
from typing import Any

from cks_runtime.runtime import Runtime

from cks_mcp.pipeline.researcher_step import TASK_TYPE as _RESEARCH_TASK_TYPE
from cks_mcp.pipeline.reviewer_step import TASK_TYPE as _REVIEW_TASK_TYPE
from cks_mcp.pipeline.schema import read_transition_log

_DEFAULT_LIMIT = 50

#: transition_log 'agent' -> cks-studio PipelineStepName. Only
#: Researcher/Reviewer are currently driven by start_pipeline
#: (Milestone 1) -- Synthesizer/Arbiter are listed per-run below purely
#: so the response shape always has all four steps, matching
#: cks-studio's PIPELINE_STEP_NAMES.
_AGENT_TO_STEP = {
    "ResearcherAgent": "Researcher",
    "SynthesizerAgent": "Synthesizer",
    "ReviewerAgent": "Reviewer",
    "ArbiterAgent": "Arbiter",
}
_STEP_NAMES = ["Researcher", "Synthesizer", "Reviewer", "Arbiter"]

#: step name -> the outbox task_type whose PENDING/DEAD entries reflect
#: that step still being queued or having failed. Only the two
#: Milestone-1 steps are currently enqueued by this pipeline.
_STEP_TASK_TYPE = {
    "Researcher": _RESEARCH_TASK_TYPE,
    "Reviewer": _REVIEW_TASK_TYPE,
}


def _load_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class _RunAccumulator:
    __slots__ = (
        "object_ids",
        "run_id",
        "session_id",
        # step -> (error, dead_letter_task_id)
        "step_failure",
        # step -> {object_id: {"status": "completed"|"pending", "at": ts}}
        "step_object_state",
        "timestamps",
    )

    def __init__(self, run_id: str, session_id: str) -> None:
        self.run_id = run_id
        self.session_id = session_id
        self.object_ids: set[str] = set()
        self.timestamps: list[str] = []
        self.step_object_state: dict[str, dict[str, dict[str, Any]]] = {
            name: {} for name in _STEP_NAMES
        }
        self.step_failure: dict[str, tuple[str | None, int | None]] = {}

    def mark_completed(self, step: str, object_id: str, timestamp: str | None) -> None:
        self.object_ids.add(object_id)
        if timestamp:
            self.timestamps.append(timestamp)
        prev = self.step_object_state[step].get(object_id)
        if prev is None or prev.get("status") != "completed":
            self.step_object_state[step][object_id] = {"status": "completed", "at": timestamp}

    def mark_pending(self, step: str, object_id: str) -> None:
        self.object_ids.add(object_id)
        self.step_object_state[step].setdefault(object_id, {"status": "pending", "at": None})

    def mark_failed(self, step: str, error: str | None, dead_letter_task_id: int | None) -> None:
        self.step_failure[step] = (error, dead_letter_task_id)

    def to_run(self) -> dict[str, Any]:
        timestamps = sorted(self.timestamps)
        started_at = timestamps[0] if timestamps else None
        updated_at = timestamps[-1] if timestamps else started_at

        steps: list[dict[str, Any]] = []
        any_failed = False
        any_active_or_partial = False
        all_researcher_reviewer_done = True

        for name in _STEP_NAMES:
            object_states = self.step_object_state[name]
            done_states = [s for s in object_states.values() if s["status"] == "completed"]
            failure = self.step_failure.get(name)

            error: str | None = None
            dead_letter_task_id: int | None = None

            if failure is not None:
                status = "failed"
                error, dead_letter_task_id = failure
                any_failed = True
            elif object_states and len(done_states) == len(object_states):
                status = "completed"
            elif done_states:
                status = "active"
            else:
                # either no object has been routed to this step at all,
                # or every object seen for it is still queued/unclaimed.
                status = "pending"

            step_started = min(
                (s["at"] for s in done_states if s.get("at")), default=None
            )
            step_completed = (
                max((s["at"] for s in done_states if s.get("at")), default=None)
                if status == "completed"
                else None
            )

            if name in ("Researcher", "Reviewer") and status != "completed":
                all_researcher_reviewer_done = False
            if status == "active":
                any_active_or_partial = True

            steps.append(
                {
                    "name": name,
                    "status": status,
                    "started_at": step_started,
                    "completed_at": step_completed,
                    "error": error,
                    "dead_letter_task_id": dead_letter_task_id,
                }
            )

        if any_failed:
            run_status = "failed"
        elif all_researcher_reviewer_done and self.object_ids:
            run_status = "completed"
        elif any_active_or_partial or timestamps:
            run_status = "running"
        else:
            run_status = "queued"

        fallback_ts = updated_at or started_at or ""

        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "status": run_status,
            "started_at": started_at or fallback_ts,
            "updated_at": updated_at or fallback_ts,
            "object_ids": sorted(self.object_ids),
            "steps": steps,
        }


async def list_pipeline_runs(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    session_id = arguments["session_id"]
    limit = arguments.get("limit") or _DEFAULT_LIMIT

    session = runtime.get_session(session_id)
    if session is None:
        return {"runs": [], "count": 0}

    runs: dict[str, _RunAccumulator] = {}

    def _get(run_id: str) -> _RunAccumulator:
        acc = runs.get(run_id)
        if acc is None:
            acc = _RunAccumulator(run_id, session_id)
            runs[run_id] = acc
        return acc

    # 1) Completed step transitions, from every object's transition_log.
    structure = getattr(session, "knowledge_structure", None)
    if structure is not None:
        for obj in structure.objects:
            identity = getattr(obj, "identity", None)
            obj_id = getattr(identity, "id", None) if identity is not None else None
            if not obj_id:
                continue
            for entry in read_transition_log(obj):
                run_id = entry.get("run_id")
                agent = entry.get("agent")
                step = _AGENT_TO_STEP.get(agent) if agent else None
                if not run_id or not step:
                    continue
                _get(run_id).mark_completed(step, str(obj_id), entry.get("timestamp"))

    # 2) Still-queued objects, from PENDING outbox tasks -- peek only,
    # never drain (this tool is read-only per its schema description).
    if runtime.storage.supports_outbox:
        for step, task_type in _STEP_TASK_TYPE.items():
            pending = await runtime.storage.list_tasks_by_type(
                task_type, session_id=session_id, drain=False
            )
            for task in pending:
                payload = _load_payload(task.payload)
                run_id = payload.get("run_id")
                object_id = payload.get("object_id")
                if not run_id or not object_id:
                    continue
                _get(run_id).mark_pending(step, str(object_id))

        # 3) Dead-lettered (permanently failed) steps.
        for step, task_type in _STEP_TASK_TYPE.items():
            dead = await runtime.storage.list_dead_letter_tasks(task_type)
            for task in dead:
                if task.session_id != session_id:
                    continue
                payload = _load_payload(task.payload)
                run_id = payload.get("run_id")
                if not run_id:
                    continue
                acc = _get(run_id)
                object_id = payload.get("object_id")
                if object_id:
                    acc.object_ids.add(str(object_id))
                acc.mark_failed(step, task.last_error, task.task_id)

    ordered = sorted(runs.values(), key=lambda acc: acc.timestamps and max(acc.timestamps) or "", reverse=True)
    result_runs = [acc.to_run() for acc in ordered[:limit]]
    return {"runs": result_runs, "count": len(result_runs)}
