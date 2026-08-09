# ADR-009: Sweeper Control Tools (`start_agent` / `stop_agent`)

**Status:** Proposed
**Related:** cks-runtime ADR-015 (Sweeper Control — owns the
`cks_sweeper_control` schema and the concurrency-lock contract this ADR
consumes), ADR-007 (CKSAgentOrchestrator)

## Context

`list_agents`/`agent_status` are read-only by design (see their own
schema docstrings and `AGENT_VISIBILITY.md`'s v1 plan). cks-runtime
ADR-015 defines the persistence (`cks_sweeper_control` table) and
concurrency-safety (`asyncio.Lock` per sweeper) needed to expose actual
`start`/`stop` control without either losing the decision across a
restart or racing two concurrent callers. This ADR is the thin
cks-mcp-side counterpart, same split as ADR-008 was for process
visibility: the schema/concurrency decision lives in cks-runtime, the
tool contract lives here.

## Decision

Two tools, thin wrappers over the sweeper instances already held in
`Runtime._sweepers` plus the new storage methods from cks-runtime
ADR-015:

- **`stop_agent(agent_id)`** — looks up `runtime._sweepers[agent_id]`;
  if absent, returns `{"agent_id": ..., "found": false}` (same
  not-an-error convention `agent_status` already uses for an unknown
  id — a config-disabled sweeper and an unrecognized `agent_id` are
  still indistinguishable here, exactly as `agent_status`'s own
  docstring already notes). If found, calls `sweeper.stop()` (now
  lock-guarded per ADR-015 §4) and writes `desired_running=False` to
  `cks_sweeper_control` via `set_sweeper_desired_running`, so the
  effect survives a server restart. Returns the sweeper's own
  `status()` dict (same shape `agent_status` returns) reflecting the
  now-stopped state.
- **`start_agent(agent_id)`** — mirror of the above: `sweeper.start()`
  plus `set_sweeper_desired_running(agent_id, True)`. Note per ADR-015
  §3, this only restarts the sweeper on **this** MCP server node — in a
  multi-node gossip deployment, other nodes whose sweeper of the same
  `agent_id` isn't currently running will not pick this up; the tool
  description states this explicitly rather than leaving it to be
  discovered.

Both are `session_id`-free, same as `list_agents`/`agent_status`.

Neither tool is named `pause_agent`/`resume_agent` — see cks-runtime
ADR-015 §5 for why pause/resume was deliberately not introduced as a
concept distinct from stop/start.

## Consequences

- No new storage code here — both tools call methods cks-runtime
  ADR-015 already defines. If that ADR's schema or lock design changes
  before implementation, this one changes with it (same relationship
  ADR-008 has to ADR-014).
- `cks-studio`'s Agent Panel (v1, currently read-only by its own
  design note) can now render a real Start/Stop button per sweeper
  card — separate, later UI work, not decided here.
- Still no equivalent tools for the four standalone-agent processes —
  those cannot be started by an MCP tool call at all (see companion
  ADR-010 / cks-runtime ADR-016 §4); this ADR is sweepers only.
