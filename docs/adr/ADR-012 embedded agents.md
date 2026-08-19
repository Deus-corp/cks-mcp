# ADR-012: Embedded Agents

**Status:** Implemented (`cks_mcp.agents.embedded_agents`, opt-in)
**Related:** cks-runtime ADR-016 (Standalone Agent Process Control),
cks-mcp ADR-008 (Standalone Agent Process Visibility), cks-mcp ADR-010
(Process Control Tool)

## Context

`cks-critic-agent`, `cks-enrichment-agent`, `cks-fork-agent`, and
`cks-pipeline-agent` are four separate console scripts an operator
currently has to launch and supervise by hand alongside the main
`cks-mcp` server, each constructing its own `Runtime` against the same
storage path. For a small/demo deployment this is friction with no
real benefit -- there's one database, one machine, and no reason the
main server process couldn't just run all four itself.

ADR-010 already ruled out the opposite direction -- an MCP tool that
spawns these as new OS *processes* -- as out of scope (cks-runtime
ADR-016 §4). That decision isn't revisited here: `cks-mcp` still does
not supervise external processes. What this ADR adds is different in
kind: running the same coroutines the console scripts already call
(`run_critic_agent`, `run_enrichment_agent`, `run_fork_agent`,
`run_pipeline_agent`) as `asyncio.Task`s on the *same* event loop and
in the *same* OS process as the main server, which is squarely within
`cks-mcp`'s own scope -- it's not spawning anything, just choosing to
await more coroutines.

## Decision

- Opt-in, off by default. `CKS_EMBEDDED_AGENTS=true` embeds all four;
  a per-agent flag (`CKS_EMBED_PIPELINE_AGENT`, `CKS_EMBED_CRITIC_AGENT`,
  `CKS_EMBED_ENRICHMENT_AGENT`, `CKS_EMBED_FORK_RESOLUTION_AGENT`) can
  override the blanket flag in either direction for that one agent.
  Each agent's own settings still come from its existing
  `*_from_env()` (poll interval, retry limits, etc.) -- only
  `storage_path` is forced to match the main server's own database, so
  there is exactly one source of truth for "where is the data" in
  embedded mode.
- Each of the four `run_*_agent()` functions gained an optional
  `stop_event: asyncio.Event | None` parameter. When omitted (the
  standalone console-script path, unchanged), the function creates its
  own `asyncio.Event` and installs `SIGTERM`/`SIGINT` handlers for it,
  exactly as before. When supplied (the embedded path), the function
  uses that event instead and does **not** touch signal handlers --
  the main server process already owns `SIGTERM`/`SIGINT`, and four
  coroutines each calling `loop.add_signal_handler` for the same
  signal on the same loop would silently clobber one another, only
  the last registration winning. This is the one behavioural change
  needed in the agents themselves; everything else about how they run
  (own `Runtime`, own `LivenessReporter`, own claim/heartbeat/
  complete-fail-dead-letter loop) is untouched.
- `cks_mcp.agents.embedded_agents.start_embedded_agents(storage_path)` reads
  the env vars, constructs each enabled agent's settings, creates its
  `stop_event`, and schedules `asyncio.create_task(...)`. Returns a
  list of handles (`process_kind`, `task`, `stop_event`).
  `stop_embedded_agents(handles)` sets every stop_event and awaits the
  tasks (bounded by `timeout`, default 10s) so each agent's own
  `finally` block runs -- `LivenessReporter.stop()` backdates its
  liveness row immediately (cks-runtime ADR-016 §3) and
  `runtime.aclose()` flushes storage -- before the task is considered
  done. Anything still running past the timeout is cancelled outright
  rather than blocking server shutdown indefinitely.
- `server.py`'s `main()` calls `start_embedded_agents(db_path)` right
  after plugin setup, only when the server is using a real persistent
  database file (`storage is None and use_persistent`) -- an in-memory
  storage fallback has nothing on disk for a second `Runtime` to open,
  so embedding is silently skipped in that case (a warning about the
  unwritable path is already printed earlier in `main()`). Shutdown
  calls `stop_embedded_agents()` before `registry.teardown_all()` and
  `runtime.aclose()`, in the existing `finally` block.
- Embedded agents remain visible through the *existing* read/write
  tools unchanged: `list_processes`/`process_status` (ADR-008) list
  them via `cks_agent_liveness` exactly like standalone processes (an
  embedded agent's `LivenessReporter` writes the same row shape, just
  from a thread inside the server's own process), and
  `request_process_stop` (ADR-010) can ask one to stop the same way.
  No new MCP tool was needed for visibility or remote stop.

## Consequences

- No new OS processes, no new IPC, no change to `cks-runtime`. The
  entire feature is ~150 lines in one new module plus four small,
  mechanical `stop_event` parameter additions.
- An operator who was already running the four console scripts
  alongside `cks-mcp` should not also set `CKS_EMBEDDED_AGENTS=true`
  -- that would run two independent pollers per queue against the
  same storage. This is a deployment-configuration concern, not
  something the code detects or prevents; the module docstring and
  this ADR call it out.
- `db_path`'s fallback-to-temp-file/in-memory-storage behaviour
  earlier in `main()` was already documented as breaking the
  standalone companion processes' ability to see the server's data
  (see the existing warning text in `server.py`); the same fallback
  now also just means embedded agents don't start at all, which is a
  strictly simpler failure mode than starting against a Runtime the
  main server isn't actually using.
- No UI changes -- `cks-studio`'s Agent Panel already reads
  `list_processes`/`process_status`, which surface embedded agents
  identically to standalone ones (same `process_kind` vocabulary, same
  `cks_agent_liveness` shape). This ADR is backend plumbing only, per
  the original request; a "run embedded / spawn standalone" toggle in
  Settings is possible future UI work, not decided here.