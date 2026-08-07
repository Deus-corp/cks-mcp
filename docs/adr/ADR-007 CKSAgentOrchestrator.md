# ADR-007

# CKSAgentOrchestrator: Coordinating Researcher → Critic → Synthesizer → Arbiter

**Status:** Proposed

**Date:** 2026-08-07

**Category:** Architecture Decision Record

---

# Context

With gossip stability deferred (see "Gossip: Recommendation" note below),
the next feature is a coordinator that runs a fixed pipeline of LLM
agents — Researcher, Critic, Synthesizer, Arbiter — against a shared
Knowledge Structure, using the CRDT machinery already validated by the
CRDT Fork Resolution Agent rather than a new message bus.

Agents do not call each other via RPC. They react to shared state — a
Blackboard / Tuple Space pattern. That pattern buys decoupling and
resilience but introduces three problems that must be solved explicitly
or the pipeline will race, loop, or duplicate work:

1. **No shared "what to do next" signal** — without an explicit state
   marker per object, every agent would have to guess whether an object
   is theirs to work on.
2. **No claim mechanism** — if two instances of the same agent wake up
   for the same object, both may invoke an LLM on it, producing two
   different results and manufacturing a fork the Fork Resolution Agent
   then has to spend cycles reconciling for no reason.
3. **No decision on how much reasoning history survives** — overwriting
   a single `pipeline_status` field discards exactly the information
   (why did Critic reject this three times) that `cks-dashboard`'s
   planned Inference Chain Inspector and Fork Diff View need.

The project's stated priority for this stage is **explainability over
latency**: CKS is a reasoning layer built around agents, knowledge
graphs, and mechanisms like `cks-fork-agent` and `LCAArbiter`. A fast
pipeline whose fork/rejection history cannot be inspected is a
regression relative to that goal, and an LLM-hallucination caught late
costs far more than a few hundred milliseconds of coordination overhead.
This ADR is written under that priority: every choice below favors a
transparent, replayable audit trail over minimizing latency, wherever
the two are in tension.

# Decision

## 1. Pipeline state lives in the data, not in the orchestrator

Every object flowing through the pipeline carries a `current_status`
field (`awaiting_research`, `awaiting_critique`, `awaiting_synthesis`,
`awaiting_arbitration`, `needs_research`, `resolved`, …) plus an
**append-only** `transition_log`. Agents only ever add entries; nothing
overwrites or deletes prior entries — see Decision 4.

An agent's read query is always "give me objects with
`current_status == X`", never "call me when something happens" alone
(see Decision 3). This makes each agent a pure function of the current
`current_status`, not of message order, which is what keeps the
pipeline safe under gossip-style delivery reordering when gossip is
eventually reintroduced (ADR-005/ADR-006, this repo; ADR-008, cks-runtime).

## 2. Claim objects before running the LLM, not after

Running an LLM is expensive (money, latency) and non-deterministic —
letting two workers both run Critic on the same object and reconciling
the fork afterward is pure waste, not resilience. Objects are therefore
**claimed** before the expensive step, using whichever mechanism matches
the deployment's storage topology:

- **Single shared Postgres/SQLite** (the default, in-process
  orchestrator target for this ADR): `SELECT ... FOR UPDATE SKIP LOCKED`
  (Postgres) or an equivalent claim-row pattern (SQLite, via a
  `claimed_by`/`claimed_at` column and a conditional `UPDATE ...
  WHERE claimed_by IS NULL`). This is transactionally exact — no
  duplicate work is possible — and requires no new infrastructure.
- **Fully decentralized, no shared database** (out of scope for
  Milestone 1, revisit only if/when gossip stability work resumes): a
  lease/claim written into the CRDT itself
  (`{"claimed_by": "...", "claim_ts": "..."}`), a short debounce window,
  then re-read to see whether this replica's claim survived merge
  (LWW or id-order tiebreak). Strictly slower and only necessary once
  there is no single database to hold a real lock against.

Given the in-process, single-storage-backend scope of Milestone 1
(Decision 5 below), `SKIP LOCKED` is what ships first. The lease/claim
path is documented here so the pipeline API doesn't have to change
shape if a decentralized deployment is added later — only the claim
implementation swaps.

## 3. Wake-up is event-driven with a fallback poll; the event is never the payload

Two extremes are both wrong for this: pure polling drives needless load
on the store as agent count grows, and pure pub/sub is not durable —
distributed systems drop notifications (a restart, a dropped
connection) and a wholly event-driven agent can wait forever.

Both problems are solved with one rule, applied uniformly whether the
backend is Postgres, SQLite, or (later) gossip:

- **Notification wakes the agent up; it never carries the task data.**
  On Postgres, this is `LISTEN`/`NOTIFY` — a write to `crdt_store`
  triggers `NOTIFY crdt_updates, '{"id": ..., "status": ...}'`, and the
  orchestrator (holding the one `LISTEN` connection for the process)
  fans that out to an in-process `asyncio.Queue`/`EventBus` that wakes
  the relevant agent pool. On SQLite (no `LISTEN`/`NOTIFY`), the
  in-process `EventBus` alone carries the signal, since every writer is
  in the same process by construction in Milestone 1.
- **On waking, the agent always re-queries the store** for the specific
  status it's looking for (`SELECT ... WHERE current_status = ...`)
  rather than trusting the notification payload. This absorbs duplicate
  or stale notifications for free and keeps the claim step (Decision 2)
  as the actual source of truth.
- **A slow fallback poll (30-60s) runs regardless of the notification
  path.** If a `NOTIFY` is dropped (process restart mid-flight, dropped
  connection), no object is stranded forever — it surfaces on the next
  poll, at low cost because the interval is long and the query is
  narrow (`WHERE current_status = X`, indexed).

## 4. Append-only transition log; reasoning content lives in separate graph nodes

Overwriting a single status field destroys exactly the material that
explainability requires: a Critic rejection cycle from three rounds ago
disappears the moment a fourth `current_status` write lands, and gossip
delivery reordering could even roll a status backward under naive
last-write-wins. Instead:

- `transition_log` is an add-only list (Add-Wins Set semantics under
  CRDT merge) of short entries: `{timestamp, agent, action,
  transitioned_to, reasoning_node_id?}`. It is what `current_status` is
  derived/cached from for fast SQL filtering (Decision 2's claim query),
  but the log is the source of truth.
- Full reasoning content — Critic's chain-of-thought, detailed
  rejection feedback, Arbiter's validation rationale — is **not**
  inlined into `transition_log` entries. It is written as its own graph
  node (`CritiqueNode`/`ReasoningNode`/etc.) and linked in via a
  semantic edge, with only the node id referenced from the log entry.
  This keeps gossip payloads and log entries small regardless of how
  verbose an agent's reasoning gets, and it means the reasoning itself
  is a first-class graph citizen — inspectable, linkable, subject to
  the same sweepers as any other object — rather than opaque log text.
- Edges connecting reasoning nodes to the objects they reason about use
  semantic types (`supports`, `refutes`, `critiques`, `resolves`, …)
  layered over the existing structural edge type used for graph
  algorithms (topological sort, orphan detection), e.g.
  `{"base_type": "depends_on", "semantic_type": "refutes"}`. Sweepers
  and cycle detection keep using `base_type`; agents, `Arbiter`, and the
  dashboard read `semantic_type`. This is additive to the existing edge
  model, not a replacement.
- Optional confidence weights (`-1.0`..`1.0`) on semantic edges are
  deferred out of Milestone 1's scope but the edge shape above leaves
  room for them (`{"semantic_type": "refutes", "weight": -0.8}`)
  without a migration. If/when introduced, weights should be computed
  by a cheap heuristic layer by default (near-zero latency, used for
  merge tie-breaking) with an LLM-evaluator pass reserved for detected
  hard conflicts — not run on every edge — consistent with this ADR's
  latency-vs-explainability tradeoff: heuristics keep the common path
  fast, the evaluator is spent only where two agents actually disagree.

## 5. Orchestrator owns lifecycle, not per-call dispatch

`CKSAgentOrchestrator` does not call agents as plain functions in
sequence. Each `AgentStep` is a long-lived `asyncio` task (co-routine)
subscribed to the events relevant to it; the orchestrator:

- starts/holds the pool of agent tasks for a pipeline run,
- owns the single `LISTEN` connection (Postgres) or in-process
  `EventBus` (SQLite) and routes wake-ups to the right agent pool,
- restarts a task that crashed (agent health), and
- publishes `AgentStepStarted`/`AgentStepCompleted` on the existing
  `runtime.events` bus (the same bus `SessionCreated`/
  `GossipConflictDetected` already use in cks-runtime) — free
  observability hook for `cks-dashboard`, no new transport.

Subprocess-based isolation is deliberately out of scope for Milestone
1: `asyncio` tasks in one process are enough to validate the CRDT
hand-off between two agents, and nothing in the `AgentStep` API below
assumes in-process execution, so moving a step behind a subprocess or
worker pool later is an implementation swap, not an API break.

## Minimal API

```python
from typing import Protocol

class PipelineContext:
    session: RuntimeSession
    crdt_store: CRDTStore
    event_bus: EventBus

class AgentStep(Protocol):
    name: str
    #: current_status value this step claims objects from
    claims_status: str

    async def run(self, ctx: PipelineContext, obj_id: str) -> None:
        """
        Idempotent: must check transition_log for its own prior
        completion against this object's current content hash before
        doing any LLM call, and must claim (Decision 2) before running.
        """

class CKSAgentOrchestrator:
    def __init__(
        self,
        session: RuntimeSession,
        crdt_store: CRDTStore,
        steps: list[AgentStep],
    ) -> None: ...

    async def run_sequential(self) -> PipelineResult:
        """Researcher -> Critic -> Synthesizer -> Arbiter, one object
        moving through claims_status transitions end to end."""

    async def run_concurrent(self, group: list[AgentStep]) -> PipelineResult:
        """Run independent steps (e.g. multiple Researcher instances
        over different objects) concurrently under one claim discipline."""
```

## Consequences

**Positive:**
- Fork Resolution Agent's job stays scoped to genuine concurrent-edit
  conflicts; claim-before-run (Decision 2) prevents the pipeline itself
  from manufacturing artificial forks.
- Every rejection cycle, every piece of Critic/Arbiter reasoning, is
  inspectable after the fact via `transition_log` + linked reasoning
  nodes — directly reusable by `cks-dashboard`'s Inference Chain
  Inspector without a new data model.
- No new network transport: reuses `runtime.events`, `CRDTStore`, and
  (for Postgres deployments) native `LISTEN`/`NOTIFY`.
- API shape does not need to change if a step later moves to a
  subprocess/worker, or if a decentralized (lease/claim) deployment is
  added — only the claim/wake-up implementation swaps per Decision 2/3.

**Negative / accepted tradeoffs:**
- Append-only logs plus separate reasoning nodes mean more objects and
  edges per pipeline run than a single overwritten status field would
  — accepted deliberately; see Context on the explainability-over-latency
  priority for this stage.
- `SKIP LOCKED` claiming ties Milestone 1 to a single shared SQL
  backend; a fully decentralized deployment needs the lease/claim path
  (Decision 2) implemented before it can run without a shared database.
- Fallback polling (Decision 3) adds a small constant background query
  load even when `LISTEN`/`NOTIFY` is healthy; accepted as the cost of
  not stranding objects on a dropped notification.

# Implementation Plan

**Milestone 1 (first target):** two agents — Researcher, Critic —
exchanging data through the CRDT store in one process.

1. `transition_log` + `current_status` fields added to the relevant
   object schema (payload-level, no cks-core structural change needed —
   confirm during implementation whether this needs a new
   `KnowledgeObject` field or fits in existing metadata).
2. `CKSAgentOrchestrator.run_sequential` with two `AgentStep`s:
   `ResearcherAgent` (writes an object with `current_status =
   "awaiting_critique"`), `CriticAgent` (claims via `SKIP LOCKED`
   equivalent, reads via `query_subgraph`, appends its verdict +
   `reasoning_node_id` to `transition_log`).
3. In-process `EventBus` wake-up (SQLite target first, since it needs
   no `LISTEN`/`NOTIFY`); Postgres `LISTEN`/`NOTIFY` wiring is a
   fast-follow once the claim/status contract is validated.
4. Idempotency check: Critic must skip re-running if `transition_log`
   already has an entry for its agent name against the current content
   hash of the object it would claim.

**Milestone 2:** Synthesizer + Arbiter added to the pipeline;
`AgentStepStarted`/`Completed` wired onto `runtime.events`; Arbiter's
`validate_knowledge` failure path writes a resolution entry back into
`transition_log` and rolls `current_status` back to the appropriate
earlier stage (with reasoning attached) rather than raising bare.

**Milestone 3:** Postgres `LISTEN`/`NOTIFY` wake-up path; confidence
weights on semantic edges (heuristic layer first, evaluator reserved
for detected hard conflicts); dashboard consumes `transition_log` +
semantic edges for Inference Chain Inspector / Fork Diff View.

---

*Gossip note:* per the earlier evaluation in this project's working
notes, gossip stability work is deferred (documented as experimental,
`CKS_GOSSIP_ENABLED=false` by default) in favor of this in-process
orchestrator for the immediate Researcher→Critic→Synthesizer→Arbiter
goal. The lease/claim and CRDT-merge-based coordination paths described
in Decision 2/3 above are written so that resuming gossip hardening
later does not require reshaping this ADR's API.
