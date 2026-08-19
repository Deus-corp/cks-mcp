"""
CKSAgentOrchestrator (ADR-007): coordinates a fixed pipeline of LLM
agents -- Researcher, Reviewer, Synthesizer, Arbiter (Milestone 1:
Researcher + Reviewer only) -- against a shared Knowledge Structure.

This is Milestone 1's shape from ADR-007's Implementation Plan: the
claim-before-run and wake-up disciplines (Decisions 2/3) are provided
by the same persistent-outbox machinery ``cks_mcp.agents.critic_agent.critic_agent``/
``cks_mcp.agents.enrichment_agent.enrichment_agent`` already use (``claim_conflict_task`` and
friends, generic over ``task_type`` -- see ``cks_mcp.agents.agent_loop``),
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
import hashlib
import json
import sys
import traceback
from dataclasses import dataclass, field
from typing import Any, Protocol

from cks_runtime.events.event_bus import EventBus
from cks_runtime.events.runtime_event import AgentStepCompleted, AgentStepStarted
from cks_runtime.runtime import Runtime

from cks_mcp.agents.agent_loop import Resolution, run_resolver_with_heartbeat
from cks_mcp.pipeline.schema import read_transition_log
from cks_mcp.pipeline.token_budget import TokenBudget
from cks_mcp.tools.claim_conflict_task.handler import claim_conflict_task
from cks_mcp.tools.complete_conflict_task.handler import complete_conflict_task
from cks_mcp.tools.dead_letter_conflict_task.handler import dead_letter_conflict_task
from cks_mcp.tools.fail_conflict_task.handler import fail_conflict_task
from cks_mcp.tools.fork_sandbox.handler import fork_sandbox
from cks_mcp.tools.merge.handler import merge_branch

_DEFAULT_MAX_RETRIES = 5
_DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 60.0
#: proxy token cost charged against ctx.token_budget for each step
#: invocation (requirement 2) -- a flat estimate rather than an exact
#: count, since the orchestrator itself never sees a step's real LLM
#: usage; a step that tracks its own usage can call
#: ``ctx.token_budget.consume()`` again with the real figure.
_ESTIMATED_TOKENS_PER_STEP_CALL = 1000

#: agent name recorded in the parent session's transition_log for
#: idempotency-cache and graceful-degradation bookkeeping entries (see
#: ``_pipeline_run_hash``/``_check_idempotency_cache`` and
#: ``_record_degradation``). Distinct from any individual step's own
#: ``name`` so these entries are never confused with a real
#: Researcher/Reviewer/... transition.
_PIPELINE_RUN_AGENT = "CKSAgentOrchestrator"


def pipeline_run_hash(
    parent_session_id: str, object_ids: list[str], schema_version: str
) -> str:
    """Deterministic hash of a pipeline run's identity (Phase 1
    idempotency, requirement 3): same parent session, same set of
    objects, same schema version => same hash, regardless of
    ``object_ids`` ordering."""
    payload = json.dumps(
        {
            "parent_session_id": parent_session_id,
            "object_ids": sorted(object_ids),
            "schema_version": schema_version,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
    #: Phase 1 isolation (requirement 1): the sandbox branch this run's
    #: steps are actually operating in, and the session it will be
    #: merged back into on success. ``None`` when a run wasn't wrapped
    #: in a sandbox (e.g. a bare ``PipelineContext`` built directly in
    #: a step's own unit test).
    sandbox_session_id: str | None = None
    parent_session_id: str | None = None
    #: Phase 1 token budgeting (requirement 2). Shared by every step in
    #: one orchestrator run; ``None`` means no budget is enforced (the
    #: orchestrator always supplies one -- see ``_ctx``).
    token_budget: TokenBudget | None = None
    #: internal: the idempotency-cache hash this run was entered under
    #: (see ``_enter_sandbox``/``_exit_sandbox``); not part of the
    #: public per-step contract, only set by the orchestrator itself.
    _run_hash: str | None = field(default=None, repr=False)


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
        ``cks_mcp.agents.critic_agent.critic_agent``/``cks_mcp.agents.enrichment_agent.enrichment_agent`` resolvers
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
    #: tasks that reached fail/dead-letter because their own
    #: ``Resolution`` was unresolved (``resolved=False``) -- a subset
    #: of ``processed``. Used by ``run_sequential``'s graceful
    #: degradation (requirement 4) to decide whether to stop before
    #: the next step.
    failed: int = 0
    #: True once this step's own queue reported ``budget_exhausted``
    #: and started skipping remaining tasks without calling them.
    budget_exhausted: bool = False


@dataclass(slots=True)
class PipelineResult:
    steps: list[StepResult]
    #: Phase 1 isolation (requirement 1): set once ``merge_branch``
    #: back into the parent session has actually succeeded. ``None``
    #: means the sandbox (if any) was left in place -- either a step
    #: failed (requirement 4's graceful degradation leaves the branch
    #: for manual analysis) or this run wasn't sandboxed at all.
    sandbox_session_id: str | None = None
    merged: bool = False
    #: Phase 1 idempotency (requirement 3): True when this result was
    #: served from a prior RESOLVED run's cache rather than actually
    #: running any steps.
    from_cache: bool = False
    #: Phase 1 graceful degradation (requirement 4): set when a step
    #: reported a genuine failure (as opposed to budget exhaustion) and
    #: the orchestrator stopped before running the remaining steps.
    degraded: bool = False
    error: str | None = None

    @property
    def total_processed(self) -> int:
        return sum(s.processed for s in self.steps)


class CKSAgentOrchestrator:
    """Owns lifecycle for a set of ``AgentStep``s over one ``Runtime``
    (ADR-007 Decision 5). Milestone 1 drives each step's queue to
    exhaustion via the same claim/heartbeat/lease-renewal loop
    ``cks_mcp.agents.agent_loop.run_resolver_with_heartbeat`` already
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
        token_budget_factory: Any = TokenBudget,
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
        #: a zero-arg callable returning a fresh ``TokenBudget`` --
        #: injectable so tests can supply a budget with a tiny cap
        #: without touching environment variables.
        self._token_budget_factory = token_budget_factory

    def _ctx(
        self,
        *,
        sandbox_session_id: str | None = None,
        parent_session_id: str | None = None,
        token_budget: TokenBudget | None = None,
    ) -> PipelineContext:
        return PipelineContext(
            runtime=self.runtime,
            event_bus=self.event_bus,
            sandbox_session_id=sandbox_session_id,
            parent_session_id=parent_session_id,
            token_budget=token_budget,
        )

    def _check_idempotency_cache(
        self, parent_session_id: str, run_hash: str
    ) -> str | None:
        """Requirement 3: has a prior run with this exact
        ``(parent_session_id, object_ids, schema_version)`` hash
        already reached ``RESOLVED``? If so, return the sandbox
        session id it was recorded against so the caller can skip
        re-running entirely.

        Looks at the *parent* session's own ``transition_log`` --
        entries this orchestrator itself appends there (see
        ``_record_cache_entry``/``_record_degradation``), never at the
        sandbox branch's log (which is closed/gone once merged).
        """
        session = self.runtime.get_session(parent_session_id)
        if session is None:
            return None
        structure = getattr(session, "knowledge_structure", None)
        if structure is None:
            return None

        marker_id = f"pipeline_run:{run_hash}"
        for obj in structure.objects:
            identity = getattr(obj, "identity", None)
            obj_id = getattr(identity, "id", None) if identity is not None else None
            if obj_id != marker_id:
                continue
            for entry in read_transition_log(obj):
                if (
                    entry.get("agent") == _PIPELINE_RUN_AGENT
                    and entry.get("run_hash") == run_hash
                    and entry.get("transitioned_to") == "resolved"
                ):
                    return entry.get("sandbox_session_id")
        return None

    async def _record_cache_entry(
        self, parent_session_id: str, run_hash: str, sandbox_session_id: str
    ) -> None:
        """Best-effort: append a RESOLVED marker for ``run_hash`` to
        the parent session's own transition_log so a future identical
        run can be served from cache (requirement 3). Failure to
        record this is not fatal to the pipeline run itself -- it just
        means the next identical run won't hit the cache."""
        try:
            from cks_mcp.tools.evolve.handler import evolve_knowledge

            op = {
                "type": "update_object",
                "object_id": f"pipeline_run:{run_hash}",
                "structure_patch": {
                    "current_status": "resolved",
                    "transition_log": [
                        {
                            "agent": _PIPELINE_RUN_AGENT,
                            "action": "pipeline_run_cached",
                            "transitioned_to": "resolved",
                            "run_hash": run_hash,
                            "sandbox_session_id": sandbox_session_id,
                        }
                    ],
                },
                "mode": "merge",
            }
            await evolve_knowledge(
                self.runtime,
                {"session_id": parent_session_id, "operations": [op]},
            )
        except Exception:  # noqa: BLE001 -- caching is best-effort, never fatal
            traceback.print_exc(file=sys.stderr)

    async def _record_degradation(
        self, parent_session_id: str, failed_step: str, detail: str
    ) -> None:
        """Requirement 4a: record graceful-degradation progress on the
        *parent* session (not the sandbox, which is left in place per
        requirement 1 for manual analysis) when a step fails and later
        steps are skipped. Best-effort, same as ``_record_cache_entry``."""
        try:
            from cks_mcp.tools.evolve.handler import evolve_knowledge

            op = {
                "type": "update_object",
                "object_id": f"pipeline_degradation:{failed_step}:{parent_session_id}",
                "structure_patch": {
                    "current_status": "needs_research",
                    "transition_log": [
                        {
                            "agent": _PIPELINE_RUN_AGENT,
                            "action": "graceful_degradation",
                            "transitioned_to": "needs_research",
                            "failed_step": failed_step,
                            "detail": detail,
                        }
                    ],
                },
                "mode": "merge",
            }
            await evolve_knowledge(
                self.runtime,
                {"session_id": parent_session_id, "operations": [op]},
            )
        except Exception:  # noqa: BLE001 -- best-effort bookkeeping, never fatal
            traceback.print_exc(file=sys.stderr)

    async def _drain_step(self, step: AgentStep, ctx: PipelineContext) -> StepResult:
        """Claim -> run -> complete/fail/dead-letter, one task_type,
        until its queue reports empty. Mirrors
        ``cks_mcp.agents.critic_agent.critic_agent._process_one``/
        ``cks_mcp.agents.enrichment_agent.enrichment_agent._process_one`` exactly, generalized
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
        processed = 0
        abandoned = 0
        failed = 0
        budget_exhausted = False
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

                # Requirement 2: check the shared per-run budget before
                # calling into the step at all -- this is the
                # orchestrator's proxy for "before the LLM call", so
                # existing steps (Researcher/Synthesizer/Reviewer/
                # Arbiter) don't need any code change to get budget
                # enforcement. ``ctx.token_budget`` is also reachable
                # from inside a step's own ``run()`` for a step that
                # wants a finer-grained check against its own actual
                # token usage.
                if budget_exhausted or (
                    ctx.token_budget is not None
                    and not ctx.token_budget.consume(_ESTIMATED_TOKENS_PER_STEP_CALL)
                ):
                    budget_exhausted = True
                    resolution = Resolution(False, "budget_exhausted")
                    lease_lost = False
                else:
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
                failed += 1
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
            failed=failed,
            budget_exhausted=budget_exhausted,
        )

    async def _enter_sandbox(
        self,
        parent_session_id: str | None,
        object_ids: list[str] | None,
        schema_version: str,
    ) -> tuple[PipelineContext, str | None, bool]:
        """Requirements 1 & 3: resolve idempotency cache, else
        ``fork_sandbox`` off ``parent_session_id`` and return a
        ``PipelineContext`` bound to the resulting branch.

        Returns ``(ctx, cached_sandbox_session_id, from_cache)``. When
        ``parent_session_id`` is ``None`` (a caller that hasn't opted
        into Phase 1 isolation yet), this is a no-op: a plain,
        unsandboxed context is returned and ``from_cache`` is always
        False, so existing callers of ``run_sequential``/
        ``run_concurrent`` keep working unchanged.
        """
        if parent_session_id is None:
            return self._ctx(token_budget=self._token_budget_factory()), None, False

        run_hash = pipeline_run_hash(parent_session_id, object_ids or [], schema_version)
        cached = self._check_idempotency_cache(parent_session_id, run_hash)
        if cached is not None:
            return (
                self._ctx(
                    sandbox_session_id=cached,
                    parent_session_id=parent_session_id,
                    token_budget=self._token_budget_factory(),
                ),
                cached,
                True,
            )

        fork_result = await fork_sandbox(self.runtime, {"session_id": parent_session_id})
        sandbox_session_id = fork_result.get("sandbox_session_id")
        if sandbox_session_id is None:
            # fork_sandbox failed (see its own 'error' field); fall
            # back to running directly against the parent rather than
            # silently losing isolation with no diagnostic.
            print(
                f"[cks-orchestrator] fork_sandbox failed for "
                f"{parent_session_id!r}: {fork_result.get('message') or fork_result.get('error')} "
                "-- running unsandboxed",
                file=sys.stderr,
            )
            return (
                self._ctx(
                    parent_session_id=parent_session_id,
                    token_budget=self._token_budget_factory(),
                ),
                None,
                False,
            )

        ctx = self._ctx(
            sandbox_session_id=sandbox_session_id,
            parent_session_id=parent_session_id,
            token_budget=self._token_budget_factory(),
        )
        ctx._run_hash = run_hash  # type: ignore[attr-defined]  # stashed for _exit_sandbox's cache write
        return ctx, sandbox_session_id, False

    async def _exit_sandbox(
        self, ctx: PipelineContext, result: PipelineResult, degraded: bool
    ) -> None:
        """Requirement 1: merge the sandbox branch back on a clean run,
        or leave it in place (for manual analysis) when a step failed.
        Requirement 3: on a successful merge, record the idempotency
        cache entry so an identical future run is served from cache."""
        result.sandbox_session_id = ctx.sandbox_session_id
        if ctx.sandbox_session_id is None or ctx.parent_session_id is None:
            return

        if degraded or any(s.error for s in result.steps):
            result.degraded = degraded
            return

        merge_result = await merge_branch(
            self.runtime,
            {
                "target_session_id": ctx.parent_session_id,
                "source_session_id": ctx.sandbox_session_id,
            },
        )
        if merge_result.get("merged"):
            result.merged = True
            run_hash = getattr(ctx, "_run_hash", None)
            if run_hash:
                await self._record_cache_entry(
                    ctx.parent_session_id, run_hash, ctx.sandbox_session_id
                )
        else:
            # A merge conflict/failure is not itself an infra crash --
            # it just means the branch stays around, same as the
            # graceful-degradation case, for a human (or a future
            # merge_branch call with 'resolutions') to sort out.
            result.error = merge_result.get("error") or "merge_branch reported a conflict"

    async def run_sequential(
        self,
        *,
        parent_session_id: str | None = None,
        object_ids: list[str] | None = None,
        schema_version: str = "v1",
    ) -> PipelineResult:
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
        without preventing later steps in this same call from running.

        Phase 1 safety infrastructure (all opt-in via
        ``parent_session_id``; omitting it reproduces the pre-Phase-1
        behavior exactly):

        - **Isolation**: every step in this call runs inside a
          ``fork_sandbox`` branch of ``parent_session_id``, merged back
          only once every step has finished cleanly.
        - **Idempotency**: if an earlier run with the same
          ``(parent_session_id, object_ids, schema_version)`` already
          reached RESOLVED, this call returns that cached result
          without running anything.
        - **Graceful degradation**: once a step reports any failed
          task (``StepResult.failed > 0``), remaining steps are
          skipped, progress is recorded on the parent session, and the
          sandbox branch is left in place rather than merged.
        """
        ctx, cached_sandbox_id, from_cache = await self._enter_sandbox(
            parent_session_id, object_ids, schema_version
        )
        if from_cache:
            return PipelineResult(
                steps=[], sandbox_session_id=cached_sandbox_id, merged=True, from_cache=True
            )

        results: list[StepResult] = []
        degraded = False
        for step in self.steps:
            step_result = await self._drain_step(step, ctx)
            results.append(step_result)
            if step_result.failed > 0 and step_result.budget_exhausted is False:
                degraded = True
                if ctx.parent_session_id is not None:
                    await self._record_degradation(
                        ctx.parent_session_id, step.name, "step reported failed task(s)"
                    )
                break
            if step_result.budget_exhausted:
                degraded = True
                if ctx.parent_session_id is not None:
                    await self._record_degradation(
                        ctx.parent_session_id, step.name, "budget_exhausted"
                    )
                break

        result = PipelineResult(steps=results)
        await self._exit_sandbox(ctx, result, degraded)
        return result

    async def run_concurrent(
        self,
        group: list[AgentStep] | None = None,
        *,
        parent_session_id: str | None = None,
        object_ids: list[str] | None = None,
        schema_version: str = "v1",
    ) -> PipelineResult:
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
        orphaned tasks outside gather's accounting.

        Same Phase 1 semantics as ``run_sequential`` (see its
        docstring) except graceful degradation cannot "stop before the
        next step" -- concurrent steps are already all in flight
        together -- so a failed step here just means the merge is
        skipped and the sandbox is left in place, same end state as
        the sequential case.
        """
        ctx, cached_sandbox_id, from_cache = await self._enter_sandbox(
            parent_session_id, object_ids, schema_version
        )
        if from_cache:
            return PipelineResult(
                steps=[], sandbox_session_id=cached_sandbox_id, merged=True, from_cache=True
            )

        steps = group if group is not None else self.steps
        results = list(await asyncio.gather(*(self._drain_step(step, ctx) for step in steps)))

        degraded = any(s.failed > 0 or s.budget_exhausted for s in results)
        if degraded and ctx.parent_session_id is not None:
            failed_step_names = ",".join(
                s.step_name for s in results if s.failed > 0 or s.budget_exhausted
            )
            await self._record_degradation(
                ctx.parent_session_id, failed_step_names or "unknown", "concurrent step(s) failed"
            )

        result = PipelineResult(steps=results)
        await self._exit_sandbox(ctx, result, degraded)
        return result