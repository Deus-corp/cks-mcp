# ADR-010: Process Control Tool (`request_process_stop`)

**Status:** Proposed
**Related:** cks-runtime ADR-016 (Standalone Agent Process Control —
owns the `cks_agent_liveness.desired_state` column and the
`LivenessReporter` wiring this ADR consumes), cks-mcp ADR-008
(Standalone Agent Process Visibility — the read side this ADR adds a
write to)

## Context

`list_processes`/`process_status` (ADR-008) are read-only. cks-runtime
ADR-016 defines a `desired_state` signal on `cks_agent_liveness` and
wires each standalone agent's existing `stop = asyncio.Event()`
shutdown path to observe it. This ADR is the thin cks-mcp-side tool
that lets a caller actually set that signal, same split pattern as
ADR-008/ADR-014 and ADR-009/ADR-015.

## Decision

One tool:

- **`request_process_stop(process_kind)`** — `process_kind` one of
  `critic`, `enrichment`, `fork_resolution`, `pipeline`, same
  vocabulary as `process_status`. Looks up the most recently-started
  instance of that kind via the same query `process_status` already
  performs (`list_agent_liveness`, filtered to the first match — most
  recent first). If none found (never seen, or the only known instance
  is already `stopped` per the TTL rule), returns
  `{"process_kind": ..., "found": false}` — mirrors `process_status`'s
  own not-an-error convention exactly, deliberately not distinguishing
  "never seen" from "was seen but is currently stopped," since
  requesting a stop on an already-stopped instance is a no-op either
  way. If found, calls `request_agent_stop(instance_id)` (cks-runtime
  ADR-016 §1) and returns `{"process_kind": ..., "instance_id": ...,
  "accepted": true}`.

`accepted: true` means the request was recorded, **not** that the
process has stopped — cks-runtime ADR-016's Consequences section spells
out the latency bound (roughly one `liveness_interval` plus any
in-flight task). The tool description says explicitly: call
`process_status(process_kind)` afterward to confirm the instance has
actually gone (it will read `stopped` promptly once exited, per ADR-016
§3's immediate-backdate mechanism — not a slow TTL wait for the
graceful-exit case).

No `request_process_start` — cks-runtime ADR-016 §4 rules out
tool-initiated process spawning entirely (out of `cks-mcp`'s process-
supervision scope); restarting a stopped agent remains whatever
external mechanism already launches these processes today. No
pause/resume tool either, for the reasons in ADR-016 §4's second
paragraph — a stop request already **is** the graceful-drain behavior
that "pause" would have meant.

## Consequences

- No new storage code here — calls straight through to
  `request_agent_stop`, defined by cks-runtime ADR-016. If that ADR's
  column or `LivenessReporter` wiring changes before implementation,
  this one changes with it.
- `cks-studio`'s Agent Panel (v2 section, currently read-only) gains a
  "Stop" action per process card — separate, later UI work, not decided
  here. No "Start" button is possible for the same reason there's no
  `request_process_start` tool.
- Together with ADR-009 (sweeper start/stop), this closes both halves
  of the "Agent Control Panel" item the original Agent Visibility plan
  deferred pending exactly these two design questions. Implementation
  of either can now proceed independently — they share no code path
  beyond both building on the read-only visibility tools already
  shipped (ADR-008/cks-runtime ADR-014 for processes, `list_agents`/
  `agent_status` for sweepers).
