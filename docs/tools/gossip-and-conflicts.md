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