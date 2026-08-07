# Gossip & Conflict Resolution

Tools for surfacing conflicts a background process found with no caller
waiting on it: a multi-agent deployment where several `cks-mcp` processes
gossip-replicate sessions to each other (`CKS_GOSSIP_ENABLED=true` — see
[Architecture](../architecture/ARCHITECTURE.md)), or a single deployment's
`InferenceStalenessSweeper` (runs by default — see
`RuntimeConfig.inference_sweep_interval`) re-checking sessions nobody has
touched in a while. Either way, something needs to resolve what comes out
of that.

## `list_gossip_conflicts`

Gossip runs as a background cycle with no caller waiting on it, so when a
remote replica's session can't be merged automatically, the conflict can't
be raised synchronously the way `merge_branch` raises one — it's escalated
instead (`GossipConflictDetected` on the Runtime `EventBus`, cks-runtime
ADR-008) and queued. `list_gossip_conflicts` is how an external Critic
agent — a separate MCP client session, human or automated, whose job is
deciding how to resolve conflicts — drains that queue.

**Parameters:** `session_id` (optional — filter to one session),
`peek` (optional, default `false` — if `true`, return matching conflicts
without removing them from the queue).

**Response**

```json
{
  "count": 1,
  "conflicts": [
    {
      "record_id": "b3f0...",
      "detected_at": 1785700000.12,
      "source_replica_id": "replica-a",
      "session_id": "s1",
      "conflicts": ["obj-42"]
    }
  ]
}
```

**Resolving what comes back.** Each record's `conflicts` list is just the
identity ids that diverged — not a diff. Follow up with
[`compare_versions`/`explain_diff`](versioning.md) against `session_id` for
the actual field-level differences, decide the outcome, then commit it
through the ordinary [`merge_branch`](branching.md) call. `record_id` is a
handle for your own bookkeeping only — the server does not track which
records you've resolved.

**Default read is destructive.** A call with `peek` omitted removes the
records it returns, the same way pulling a message off a work queue does —
otherwise "how many conflicts are outstanding" could never be answered by
polling. If several agents (or one agent polling from multiple places)
need to see the same conflict, pass `peek: true` and manage de-duplication
yourselves.

**Nothing to return.** An empty list means either gossip isn't enabled on
this process, or nothing has conflicted since the last drain — the two
aren't distinguishable from this tool alone; check server startup logs for
`[CKS-MCP] Gossip enabled: ...` to tell them apart.

## `list_inference_conflicts`

A background `InferenceStalenessSweeper` (cks-runtime, ADR-009) periodically
re-checks recently-modified sessions for two reasoning-staleness diagnostics
(`CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT`, `CKS-EXT-STALE-PREMISE`) that
`validate_knowledge`/`evolve_knowledge` only ever catch when *that session's
own caller* happens to opt into them. A conflict that arises because a
*different* agent's commit made an existing belief stale has no synchronous
caller to raise to — the same reason gossip conflicts are escalated as an
event rather than an exception — so it's published as
`InferenceConflictDetected` and queued separately from gossip conflicts
(different shape: no `source_replica_id`, a single-structure belief
conflict rather than a merge conflict between replicas — see
cks-runtime's ADR-009 for why the two aren't folded together).
`list_inference_conflicts` drains that queue.

**Parameters:** `session_id` (optional — filter to one session),
`peek` (optional, default `false` — if `true`, return matching findings
without removing them from the queue).

**Response**

```json
{
  "count": 1,
  "conflicts": [
    {
      "record_id": "9ac1...",
      "detected_at": 1785700400.55,
      "session_id": "s1",
      "version_id": "v7",
      "diagnostics": [
        {
          "code": "CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT",
          "severity": "WARNING",
          "message": "2 active InferenceStep(s) reach conclusion 'obj-42' with disagreeing confidence values (0.9: ['step-a'], 0.4: ['step-b']).",
          "location": "step-a"
        }
      ]
    }
  ]
}
```

**Resolving what comes back.** For a `CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT`
entry, the disputed conclusion id is named in `message` in quotes (`location`
is the first conflicting `InferenceStep`'s id, not the conclusion) — read it
from there and call `arbitrate_inference_conflict` with that `session_id`
and `conclusion_id` to resolve it, same as resolving one found any other
way. A `CKS-EXT-STALE-PREMISE` entry has no single conclusion to hand that
tool directly — it names an `InferenceStep` (`location`) citing a
since-superseded premise; use [`explain_knowledge`](lifecycle.md) on the
cited step to see the current one, and record a fresh `RecordInference` if
the premise citation should be updated.

**Default read is destructive**, same as `list_gossip_conflicts` above —
pass `peek: true` to keep entries queued for another reader.

**Nothing to return.** An empty list means either the sweeper is disabled
(`inference_sweep_interval=None`) or nothing new has been found since the
last drain. Unlike gossip, the sweeper runs by default, so an empty result
on a fresh server usually just means no sweep has found anything yet.

## `resolve_gossip_conflict`

The counterpart to `arbitrate_inference_conflict` for the structural merge
conflicts `list_gossip_conflicts` drains, closing the asymmetry where those
required a hand-rolled `merge_branch(..., resolutions=...)` call while
inference conflicts already had LLM assistance. Internally it just probes
with `merge_branch(target_session_id, source_session_id)` and, if that comes
back with `conflicts` instead of `merged: true`, either returns them for the
caller to resolve or — with `auto_resolve: true` — resolves them itself via
an LLM call and re-applies the merge with the resulting `resolutions`.

**Parameters:** `target_session_id`, `source_session_id` (both required),
`auto_resolve` (optional, default `false`), `model` / `max_tokens`
(optional overrides for the `auto_resolve` LLM call).

- Without `auto_resolve`: returns `{"merged": false, "conflicts": [...],
  "policy": "..."}` — the same conflict shape `merge_branch` itself returns,
  plus the resolution policy text, so an interactive client (typically
  already an LLM) can decide and call `merge_branch` with `resolutions`
  directly.
- With `auto_resolve: true`: makes one LLM call over the conflict list using
  the same `CKS_LLM_PROVIDER` (`auto` | `ollama` | `anthropic`) dispatch as
  `arbitrate_inference_conflict`, then calls `merge_branch` again with the
  parsed `resolutions` and returns that result.
- If the probe merge already succeeds (no conflicts), returns that
  `merge_branch` result unchanged — this tool never merges a second time in
  that case.

Session validation (existence and open state) for both `target_session_id`
and `source_session_id` is enforced the same way `merge_branch` enforces it
for its `target_session_id`.

## `refresh_verification`

Re‑verifies a provenance source whose `VerificationRecord` is older than
the TTL (escalated by `ProvenanceStalenessSweeper`, cks‑runtime ADR‑010).
Calls `verify_source` with the original `record_id`, `subject_id`, and
`source_url`, and commits the fresh record when `commit: true` is set.
Fully mechanical — no LLM call.

**Parameters:** `session_id`, `record_id`, `subject_id`, `source_url`,
`commit` (optional, default `false`).

## `resolve_temporal_conflict`

Resolves a `temporal_conflict` task (escalated by `TemporalStalenessSweeper`,
cks‑runtime ADR‑011) for an object whose `valid_until` has expired.
Supports three actions:
- `bump` — extends `valid_until` by `extend_by_days` days (default 30).
- `archive` — marks the object as `archived` and clears `valid_until`.
- `ignore` — acknowledges the conflict without any modification.
All actions are mechanical (no LLM) and are applied via `evolve_knowledge`
when `commit: true` is set.

**Parameters:** `session_id`, `object_id`, `action` (`"bump"`/`"archive"`/`"ignore"`),
`extend_by_days` (for `bump`, default 30), `commit` (optional, default `false`).

## Critic Agent (autonomous)

`cks-critic-agent` is a separate console process that runs alongside the
main server. It shares the same database (SQLite or Postgres,
`CKS_MCP_DB_PATH`) and autonomously polls the persistent outbox for
`gossip_conflict` and `inference_conflict` tasks. When it finds one it
attempts to resolve it:

- `gossip_conflict` → calls `merge_branch` with the task's recorded
  `source_session_id`. A clean merge completes the task; a structural
  conflict dead-letters it for a human to review.
- `inference_conflict` → resolves both `CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT`
  (batch `arbitrate_inference_conflict(auto_resolve=True, commit=True)`) and
  `CKS-EXT-STALE-PREMISE` (mechanical rewrite via `stale_premise_ids`) in one
  combined `Resolution`. A single task may contain both diagnostic types; the
  agent handles them separately.

Tasks the agent cannot resolve after `CKS_CRITIC_MAX_RETRIES` attempts are
placed in the dead-letter queue for manual inspection.

**Start:** `CKS_MCP_DB_PATH=~/.cks-mcp/cks_mcp.db cks-critic-agent`

**Environment variables:**
- `CKS_MCP_DB_PATH` — path to the shared database (defaults to
  `~/.cks-mcp/cks_mcp.db`)
- `CKS_CRITIC_POLL_INTERVAL` — outbox poll interval in seconds (default 5)
- `CKS_CRITIC_MAX_RETRIES` — number of resolution attempts before
  dead-lettering (default 5)

---

## Critic Agent tool suite

These tools are not intended for ordinary MCP clients — they were built
specifically for `cks-critic-agent`, which runs as a separate process and has
no access to the main server's `ConflictInbox`. Instead it reads and modifies
the persistent outbox directly through the shared `cks_outbox_tasks` table.

| Tool | Purpose |
|---|---|
| `claim_conflict_task` | Atomically claims one task from the outbox (`gossip_conflict` or `inference_conflict`) and marks it `IN_PROGRESS` |
| `complete_conflict_task` | Removes a successfully resolved task from the outbox |
| `fail_conflict_task` | Reschedules a task as `PENDING` with exponential backoff for a later retry |
| `dead_letter_conflict_task` | Moves a task to `DEAD` status after the retry limit is exhausted |
| `list_dead_lettered_conflicts` | Lists every dead-lettered task for manual audit |

All five return `"supported": false` on storage backends that do not
implement the outbox (e.g. the default `InMemoryStorage`).

---

## Dead-letter queue inspection

Tasks that `cks-critic-agent` could not resolve even after several attempts
remain in `cks_outbox_tasks` with status `DEAD`. Inspect them with
`list_dead_lettered_conflicts` (optionally filtered by `task_type`):

```json
{
  "method": "tools/call",
  "params": {
    "name": "list_dead_lettered_conflicts",
    "arguments": {"task_type": "inference_conflict"}
  }
}
```

## Enrichment Agent (autonomous)

`cks-enrichment-agent` grows the graph from external sources. It polls the
outbox for `enrichment_request` tasks (enqueued via the `request_enrichment`
tool), searches Wikipedia and arXiv, filters and scores candidates, respects
`robots.txt`, ingests promising URLs, and links the resulting `Document`
objects back to the original object via `enriched_by` relations — all as a
single atomic `evolve_knowledge` call.

- **Query:** from the task's `query` field, or the target object's name.
- **Filters:** structural low‑value URL patterns + operator‑configured
  domain allow/block lists (see `CKS_ENRICHMENT_ALLOW_*` / `CKS_ENRICHMENT_BLOCK_*`).
- **Scoring:** domain authority + query relevance. Only candidates above
  `CKS_ENRICHMENT_MIN_SCORE` (default 0.5) are fetched.
- **Robots.txt:** checked before every unattended fetch.
- **Provenance:** each ingested source is verified with `verify_source`.

**Start:** `CKS_MCP_DB_PATH=~/.cks-mcp/cks_mcp.db cks-enrichment-agent`

**Environment variables:** `CKS_MCP_DB_PATH`, `CKS_ENRICHMENT_POLL_INTERVAL`,
`CKS_ENRICHMENT_MAX_RETRIES`, `CKS_ENRICHMENT_MIN_SCORE`, `CKS_ENRICHMENT_MAX_INGESTS`,
and adapter‑specific overrides (see `cks_mcp/enrichment_agent.py`).

## Fork Resolution Agent (autonomous CRDT fork resolution)

`cks-fork-agent` resolves `crdt_fork` tasks produced by the CRDT adapter
(ADR-013 Stage 2) when two replicas concurrently write the same pointer
key. It works out‑of‑the‑box against the same SQLite/Postgres database as
the main server, requiring no LLM access — it's purely mechanical.

**Resolution policy**
1. **Causal ordering** — if one object's `VersionVector` strictly dominates
   the others, it wins.
2. **Most‑recent pointer** — otherwise, the object with the most recent
   `created_at` on the live MV‑Register pointer row wins.
3. **Deterministic tie‑break** — otherwise, the alphabetically‑first
   `object_id` wins. Every replica computes object ids identically
   (content hashes), so all replicas converge on the same winner
   independently.

**Start:**
```bash
CKS_MCP_DB_PATH=~/.cks-mcp/cks_mcp.db cks-fork-agent
```

**Environment variables:**
- `CKS_MCP_DB_PATH` — shared storage path
- `CKS_FORK_AGENT_POLL_INTERVAL` — seconds between outbox polls (default 30)
- `CKS_FORK_AGENT_MAX_RETRIES` — attempts before dead‑lettering (default 3)
- `CKS_FORK_AGENT_HEARTBEAT_INTERVAL` — lease renewal interval (default 60)

See [CRDT Fork Resolution Case Study](../case-studies/crdt-fork-resolution.md)
for a walk‑through.