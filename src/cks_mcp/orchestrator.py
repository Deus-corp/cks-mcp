"""
CKSAgentOrchestrator (ADR-007): coordinates a fixed pipeline of LLM
agents -- Researcher, Reviewer, Synthesizer, Arbiter (Milestone 1:
Researcher + Reviewer only) -- against a shared Knowledge Structure.

This is Milestone 1's shape from ADR-007's Implementation Plan: the
claim-before-run and wake-up disciplines (Decisions 2/3) are provided
by the same persistent-outbox machinery ``cks_mcp.critic_agent``/
``cks_mcp.enrichment_agent`` already use (``claim_conflict_task`` and
friends, generic over ``task_type`` -- see ``cks_mcp.agent_loop``),
rather than new infrastructure. Each pipeline step is registered under
its own ``task_type`` (``pipeline_research_request``,
``pipeline_review_request``, ...); the outbox row *is* the claim, so
two workers racing on the same object is already excluded by
``dequeue_next_outbox_task``'s atomic claim -- ADR-007 Decision 2's
"single shared Postgres/SQLite" path. The lease/claim CRDT path
described there for a fully decentralized deployment is out of scope
for Milestone 1, same as it is for Critic/Enrichment Agent.

``AgentStepStarted``/``AgentStepCompleted`` are published on the
``Runtime``'s existing ``event_bus`` per Decision 5 -- a free
observability hook for ``cks-dashboard``, no new transport.
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from dataclasses import dataclass
from typing import Any, Protocol

from cks_runtime.events.event_bus import EventBus
from cks_runtime.events.runtime_event import AgentStepCompleted, AgentStepStarted
from cks_runtime.runtime import Runtime

from cks_mcp.agent_loop import Resolution, run_resolver_with_heartbeat
from cks_mcp.tools.claim_conflict_task.handler import claim_conflict_task
from cks_mcp.tools.complete_conflict_task.handler import complete_conflict_task
from cks_mcp.tools.dead_letter_conflict_task.handler import dead_letter_conflict_task
from cks_mcp.tools.fail_conflict_task.handler import fail_conflict_task

_DEFAULT_MAX_RETRIES = 5
_DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 60.0


@dataclass(slots=True)
class PipelineContext:
    """Everything an ``AgentStep`` needs to run against one object.

    ``event_bus`` defaults to ``runtime.events`` when the ``Runtime``
    exposes one; steps should still prefer ``ctx.event_bus`` over
    reaching into ``ctx.runtime`` directly so a step's own tests can
    swap in a bare ``EventBus()``.

    There is deliberately no ``session_id`` field here: every claimed
    outbox task already carries its own ``session_id`` (a single
    orchestrator instance can drain tasks belonging to many sessions
    in the same run), and both ``ResearcherStep``/``ReviewerStep`` read
    it from the task dict they're given, not from this context. An
    earlier revision carried a ``session_id`` here left over from a
    single-session design; it was unused by every step and has been
    removed rather than left as a misleading, always-stale field.
    """

    runtime: Runtime
    event_bus: EventBus


class AgentStep(Protocol):
    """One stage of the pipeline (Researcher, Reviewer, ...).

    ``task_type`` is the outbox queue this step claims from --
    Milestone 1's stand-in for ADR-007's "objects with
    ``current_status == X``" read query (Decision 1): rather than
    scanning the whole structure for a status match, the object was
    already enqueued onto this task_type by whichever step (or tool,
    e.g. a ``request_review``-style enqueue) put it into that status,
    exactly as ``request_enrichment`` enqueues ``enrichment_request``
    for the Enrichment Agent today.
    """

    name: str
    #: current_status value this step claims objects from (see
    #: cks_mcp.pipeline.schema.PipelineStatus)
    claims_status: str
    #: outbox task_type this step's queue uses
    task_type: str

    async def run(self, ctx: PipelineContext, task: dict[str, Any]) -> Resolution:
        """
        Idempotent: must check ``transition_log`` for its own prior
        completion against this object's current content before doing
        any LLM call (see ``cks_mcp.pipeline.schema.has_agent_transitioned``),
        and must have already been claimed (the orchestrator's job, via
        ``claim_conflict_task``) before running.

        ``task`` is the claimed outbox task dict (``task_id``,
        ``task_type``, ``session_id``, ``payload``, ``retry_count``) --
        the same shape ``claim_conflict_task`` returns and
        ``cks_mcp.critic_agent``/``cks_mcp.enrichment_agent`` resolvers
        already consume.
        """
        ...


@dataclass(slots=True)
class StepResult:
    step_name: str
    task_type: str
    #: tasks that reached complete/fail/dead-letter (successfully or
    #: not) -- see ``PipelineResult.total_processed``.
    processed: int = 0
    #: tasks abandoned mid-run because another worker reclaimed their
    #: lease (see ``run_resolver_with_heartbeat``) -- deliberately
    #: excluded from ``processed`` since nothing was actually completed,
    #: failed, or dead-lettered for these; kept separate so callers can
    #: still see them for observability.
    abandoned: int = 0
    #: set when the drain loop itself aborted on an infrastructure
    #: failure (claim/complete/fail/dead-letter/event-bus call raised)
    #: rather than an individual task failing normally. ``None`` means
    #: the loop ran to exhaustion (queue empty) without incident.
    error: str | None = None


@dataclass(slots=True)
class PipelineResult:
    steps: list[StepResult]

    @property
    def total_processed(self) -> int:
        return sum(s.processed for s in self.steps)


class CKSAgentOrchestrator:
    """Owns lifecycle for a set of ``AgentStep``s over one ``Runtime``
    (ADR-007 Decision 5). Milestone 1 drives each step's queue to
    exhaustion via the same claim/heartbeat/lease-renewal loop
    ``cks_mcp.agent_loop.run_resolver_with_heartbeat`` already
    provides -- long-lived per-step ``asyncio`` tasks subscribed to
    ``LISTEN``/``NOTIFY`` wake-ups are Milestone 3 scope (ADR-007);
    this class's public shape does not need to change to add that."""

    def __init__(
        self,
        runtime: Runtime,
        steps: list[AgentStep],
        *,
        event_bus: EventBus | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        heartbeat_interval: float = _DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        self.runtime = runtime
        self.steps = steps
        runtime_bus = getattr(runtime, "events", None)
        if event_bus is not None:
            self.event_bus = event_bus
        elif runtime_bus is not None:
            self.event_bus = runtime_bus
        else:
            self.event_bus = EventBus()
        self.max_retries = max_retries
        self.heartbeat_interval = heartbeat_interval

    def _ctx(self) -> PipelineContext:
        return PipelineContext(runtime=self.runtime, event_bus=self.event_bus)

    async def _drain_step(self, step: AgentStep) -> StepResult:
        """Claim -> run -> complete/fail/dead-letter, one task_type,
        until its queue reports empty. Mirrors
        ``cks_mcp.critic_agent._process_one``/
        ``cks_mcp.enrichment_agent._process_one`` exactly, generalized
        over ``AgentStep`` instead of a fixed resolver map.

        Never raises: an infrastructure failure (``claim_conflict_task``/
        ``complete_conflict_task``/etc. or ``event_bus.publish`` itself
        raising, as opposed to a task's own resolver failing normally)
        aborts *this step's* loop and is reported via
        ``StepResult.error``, rather than propagating -- ``run_concurrent``
        runs every step's drain loop under the same ``asyncio.gather``,
        and one step's transport/DB hiccup must not take down sibling
        steps' already-in-flight drains or leave them as orphaned
        background tasks outside gather's accounting. Any task already
        claimed when the loop aborts is left claimed; its lease simply
        expires and gets reclaimed by a future drain, same as the
        ``lease_lost`` case below.
        """
        ctx = self._ctx()
        processed = 0
        abandoned = 0
        error: str | None = None

        try:
            while True:
                claim_result = await claim_conflict_task(
                    self.runtime, {"task_type": step.task_type}
                )
                if not claim_result.get("supported"):
                    print(
                        f"[cks-orchestrator] storage backend does not support the "
                        f"persistent outbox -- nothing to do for step {step.name!r} "
                        f"(task_type={step.task_type!r}).",
                        file=sys.stderr,
                    )
                    break

                task = claim_result.get("task")
                if task is None:
                    break

                task_id = task["task_id"]
                object_id = str((task.get("payload") or {}).get("object_id") or "")

                await self.event_bus.publish(
                    AgentStepStarted(
                        step_name=step.name,
                        session_id=task["session_id"],
                        object_id=object_id,
                        claims_status=step.claims_status,
                    )
                )

                ctx_for_run = ctx  # PipelineContext, captured for the closure below

                async def _resolver(rt: Runtime, t: dict[str, Any], _step: AgentStep = step, _ctx: PipelineContext = ctx_for_run) -> Resolution:
                    return await _step.run(_ctx, t)

                try:
                    resolution, lease_lost = await run_resolver_with_heartbeat(
                        self.runtime, _resolver, task, task_id, self.heartbeat_interval
                    )
                except Exception as exc:  # noqa: BLE001 -- an individual task's resolver failing must not crash the drain loop
                    resolution = Resolution(False, f"unexpected exception: {exc}")
                    lease_lost = False
                    traceback.print_exc(file=sys.stderr)

                if lease_lost:
                    abandoned += 1
                    print(
                        f"[cks-orchestrator] lost lease on {step.task_type} "
                        f"task_id={task_id} while running step {step.name!r} "
                        "(reclaimed by another worker) -- abandoning without "
                        "completing/failing/dead-lettering it",
                        file=sys.stderr,
                    )
                    continue

                if resolution.resolved:
                    await complete_conflict_task(self.runtime, {"task_id": task_id})
                    processed += 1
                    await self.event_bus.publish(
                        AgentStepCompleted(
                            step_name=step.name,
                            session_id=task["session_id"],
                            object_id=object_id,
                            succeeded=True,
                            transitioned_to=resolution.detail or "",
                        )
                    )
                    continue

                task_error = resolution.detail or "unknown error"
                next_retry_count = task["retry_count"] + 1
                if next_retry_count >= self.max_retries:
                    await dead_letter_conflict_task(
                        self.runtime, {"task_id": task_id, "error": task_error}
                    )
                else:
                    await fail_conflict_task(
                        self.runtime,
                        {"task_id": task_id, "retry_count": next_retry_count, "error": task_error},
                    )
                processed += 1
                await self.event_bus.publish(
                    AgentStepCompleted(
                        step_name=step.name,
                        session_id=task["session_id"],
                        object_id=object_id,
                        succeeded=False,
                        error=task_error,
                    )
                )
        except Exception as exc:  # noqa: BLE001 -- infra failure; see docstring above
            error = f"drain loop aborted: {exc}"
            traceback.print_exc(file=sys.stderr)

        return StepResult(
            step_name=step.name,
            task_type=step.task_type,
            processed=processed,
            abandoned=abandoned,
            error=error,
        )

    async def run_sequential(self) -> PipelineResult:
        """Drain each step's queue in order: Researcher fully, then
        Reviewer fully, etc. -- one object at a time moving through
        ``claims_status`` transitions end to end, as ADR-007's Minimal
        API describes. Draining Researcher before Reviewer starts is a
        Milestone 1 simplification (no long-lived concurrent step
        tasks yet); it is still correct because a Researcher-produced
        object's own ``pipeline_review_request`` enqueue (done by the
        Researcher step itself) doesn't depend on Reviewer having
        already been drained.

        ``_drain_step`` never raises (see its docstring), so one step's
        infrastructure failure is reported on its own ``StepResult``
        without preventing later steps in this same call from running."""
        results = [await self._drain_step(step) for step in self.steps]
        return PipelineResult(steps=results)

    async def run_concurrent(self, group: list[AgentStep] | None = None) -> PipelineResult:
        """Run independent steps concurrently under one claim
        discipline (ADR-007 Minimal API) -- safe because each step's
        claim comes from its own outbox task_type/queue, so there is
        no shared mutable state between the concurrent drains besides
        the outbox itself, which is already claim-safe (Decision 2).

        ``_drain_step`` catches its own infrastructure failures and
        returns a ``StepResult`` rather than raising, so this
        ``asyncio.gather`` never needs ``return_exceptions=True``: a
        DB/transport hiccup in one step's drain surfaces as that
        step's ``StepResult.error`` instead of cancelling the whole
        call and leaking the other steps' still-running drains as
        orphaned tasks outside gather's accounting."""
        steps = group if group is not None else self.steps
        results = await asyncio.gather(*(self._drain_step(step) for step in steps))
        return PipelineResult(steps=list(results))