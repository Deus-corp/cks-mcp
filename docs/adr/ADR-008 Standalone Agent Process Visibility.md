# ADR-008: Standalone Agent Process Visibility (`list_processes` / `process_status`)

**Status:** Proposed
**Related:** cks-runtime ADR-014 (Standalone Agent Liveness Heartbeat —
owns the `cks_agent_liveness` schema and the heartbeat-writer contract
this ADR consumes), ADR-007 (CKSAgentOrchestrator)

## Context

`list_agents`/`agent_status` cover only in-process sweepers (see their
own schema docstrings) and explicitly do not cover the four standalone
agent processes (Critic, Enrichment, Fork Resolution, Pipeline). cks-mcp
ADR-014 (in cks-runtime) defines a `cks_agent_liveness` table and a
per-process heartbeat writer for those four processes. This ADR is the
thin cks-mcp-side counterpart: the two new MCP tools that read that
table, kept deliberately separate from `list_agents`/`agent_status` —
see cks-runtime ADR-014 §4 for the reasoning on why these are not
merged into the sweeper tools.

## Decision

Add two read-only tools, thin wrappers over
`storage.list_agent_liveness()`:

- **`list_processes`** — no arguments, returns every known process
  instance with a computed `status: "alive" | "stopped"` field (TTL
  rule: `now - last_heartbeat_at <= 3 * liveness_interval_s`, see
  cks-runtime ADR-014 §3).
- **`process_status(process_kind)`** — `process_kind` one of `critic`,
  `enrichment`, `fork_resolution`, `pipeline`; returns the most
  recently-started instance of that kind, or
  `{"process_kind": ..., "found": false}` if no instance has ever
  reported in — mirrors `agent_status`'s not-an-error convention for
  unknown/never-seen ids.

Both are `session_id`-free, same as `list_agents` — this data isn't
scoped to a session or graph.

Same process-locality caveat as `list_agents`/`agent_status` and
`get_metrics`'s `critic_agent_metrics` must be stated in both tool
descriptions: `list_processes`/`process_status` report what's in the
shared `cks_agent_liveness` table (written by whichever process
instances are or were running against this storage backend), not "only
this MCP server's own process" — unlike `list_agents`, which genuinely
is this-process-only. Getting this distinction wrong in the docstring
would mislead a caller running against a multi-node deployment.

## Consequences

- No new storage code here — this ADR only adds the tool layer on top
  of what cks-runtime ADR-014 ships. If that ADR's schema changes
  before implementation, this one changes with it.
- `cks-studio`'s Agent Panel gets a second data source
  (`listProcesses()`) to add as a separate card group, per the v1 panel
  plan's own note that this was intentionally deferred.
- Still no `start`/`stop`/`pause`/`resume` here. Those remain blocked on
  a separate Control Panel design (signal/IPC mechanism for standalone
  processes; concurrent-caller semantics for sweeper start/stop) — not
  decided by this ADR.
