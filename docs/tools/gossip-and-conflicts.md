# Gossip & Conflict Resolution

Tools for a multi-agent deployment where several `cks-mcp` processes
gossip-replicate sessions to each other (`CKS_GOSSIP_ENABLED=true` — see
[Architecture](../architecture/ARCHITECTURE.md)) and something needs to
resolve the conflicts that come out of that.

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
