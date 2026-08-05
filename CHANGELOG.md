# Changelog


---

## [1.41.0] - 2026-08-05

### Added
- **Plugin framework** (`src/cks_mcp/plugin.py`) – a new `CksPlugin` abstract base class and a `PluginRegistry` for managing optional, dynamically‑loaded functionality. Plugins declare their dependencies via `is_available()`, initialise themselves through `setup(runtime, config)`, and cleanly shut down with `teardown(handle)`.
- **`FastEmbedPlugin`** (`src/cks_mcp/plugins/fastembed_plugin.py`) – extracts the existing fastembed/HuggingFace embedding initialisation from `server.py` into a proper plugin. Automatically selected when the `fastembed` package is installed.
- **`GossipPlugin`** (`src/cks_mcp/plugins/gossip_plugin.py`) – extracts the existing gossip transport initialisation from `server.py` into a proper plugin. Requires `aiohttp` (`pip install cks-mcp[gossip]`) and is enabled with `CKS_GOSSIP_ENABLED=true`.
- **`list_plugins` MCP tool** – returns every registered plugin together with its description and whether it is currently available (`is_available()`).
- `server.py` now uses `PluginRegistry` instead of manually wiring the embedding and gossip subsystems.
- New tests in `tests/test_plugin.py`, `tests/plugins/`, and `tests/tools/list_plugins/`.
- Tool count increased from 45 to 46 (`test_server.py` updated).

---

## [1.40.0] - 2026-08-05

### Added
- **Backup & migration tools (ADR-012)** – three new MCP tools for exporting, importing, and migrating data between storage backends:
  - `export_storage` – saves a complete dump of all sessions, versions, graphs, embeddings, and outbox tasks to a JSON file. Returns the file path and a summary.
  - `import_storage` – restores data from a previously created dump into the current backend (with `clear` or `merge` modes).
  - `migrate_storage` – transfers data from the current backend to a new one (SQLite or Postgres), creating a new file/database without replacing the active `runtime.storage`.
- All three tools are mechanical (no LLM). Registered in `registry.py` under the Export & Observability group.
- Tool count increased from 42 to 45 (`test_server.py` updated).
- New tests in `tests/tools/export_storage/`, `tests/tools/import_storage/`, `tests/tools/migrate_storage/`.

---

## [1.39.0] - 2026-08-05

### Added
- **`resolve_contradiction` tool** – resolves `contradiction_detected` tasks escalated by `ContradictionSweeper` (cks‑runtime v1.40.0). Two modes:
  * *Read‑only* (no `contradiction_ids`) – returns every currently‑live contradiction in the session, each with a stable `id` and its participating `relation_ids`.
  * *Resolve* (`contradiction_ids` + `commit: true`) – removes the alphabetically‑first conflicting relation for each contradiction via `evolve_knowledge`. Fully mechanical, no LLM call.
- **`contradiction_detected` support in `critic_agent.py`** – the Critic Agent now polls for `contradiction_detected` tasks (escalated by `ContradictionSweeper`) alongside the other four task types. Resolution calls `resolve_contradiction(contradiction_ids=[location], commit=True)`. An already‑resolved contradiction is treated as a success, not a retryable failure.
- Tool count increased from 41 to 42. New tests in `tests/tools/resolve_contradiction/test_handler.py` and `tests/test_critic_agent.py` covering mutual‑exclusion and functional‑relation violations, dry‑run vs commit, unknown ids, and the Critic Agent's dispatch path.

### Changed
- `critic_agent.py` now manages five task types (gossip, inference, provenance, temporal, contradiction). Docstring and `run_once` test updated accordingly.

---

## [1.38.0] - 2026-08-04

### Added
- **Memory Agent v2: graph freshness + gallery.** Two new MCP tools building on the `graph_registry` (Memory Agent v1):
  - `check_graph_freshness(name)` – read-only check of whether a registered graph is still fresh, using the same TTL `GraphFreshnessSweeper` (`cks-runtime` 1.39.0) applies in the background. Returns `{"fresh": true}` or `{"fresh": false, "last_updated": ..., "ttl_days": ...}`; `{"found": false}` if the graph isn't registered.
  - `search_graphs(query, tag?, public_only?)` – free-text, case-insensitive search over registered graphs' `name`/`description`/`tags`, so a caller can discover a graph to resume with `get_graph` without already knowing its exact name.
- `register_graph` now accepts an optional `public: bool = false` parameter, opting a graph into the gallery (discoverable by other callers, not just by exact name).
- `list_graphs` now accepts an optional `public_only: bool = false` parameter to restrict results to public graphs.
- New unit tests in `tests/tools/check_graph_freshness/` and `tests/tools/search_graphs/`; `tests/tools/register_graph/` and `tests/tools/list_graphs/` updated for the new parameters.
- Tool count increased from 39 to 41 (`test_server.py` updated).

### Requires
- `cks-runtime >= 1.39.0` for the `graph_registry.public` column and `RuntimeConfig.graph_freshness_ttl_seconds`.

---

## [1.37.0] - 2026-08-04

### Added
- **Memory Agent v1: graph registry tools.** Three new MCP tools that let LLMs (and humans) save, find, and reuse Knowledge Graphs across conversations by registering them under memorable names:
  - `register_graph(name, session_id, description?, tags?)` – register or update a named reference to an existing session's graph.
  - `get_graph(name)` – look up a registered graph and return its `session_id` and metadata, or `{"found": false}`.
  - `list_graphs(tag?)` – list all registered graphs, most recently updated first, optionally filtered by tag substring.
- The tools write to the `graph_registry` table added in `cks-runtime` 1.38.0, which is automatically created on first use in SQLite and Postgres backends. `InMemoryStorage` supports them for testing.
- New unit tests in `tests/tools/register_graph/`, `tests/tools/get_graph/`, and `tests/tools/list_graphs/`.
- Tool count increased from 36 to 39 (`test_server.py` updated).

---

## [1.36.0] - 2026-08-04

### Added
- **`temporal_conflict` support in `critic_agent.py`** – the Critic Agent now polls for `temporal_conflict` tasks (escalated by `TemporalStalenessSweeper`, cks‑runtime ADR‑011) alongside `gossip_conflict`, `inference_conflict`, and `provenance_conflict`. Resolution uses a safe default policy — `resolve_temporal_conflict(action="bump", extend_by_days=30, commit=True)` — rather than guessing whether the fact should be archived.
- New tests for `resolve_provenance_conflict` and `resolve_temporal_conflict` in `tests/test_critic_agent.py`, covering missing payload keys, successful resolution, tool errors, and commit failures.
- `test_run_once_drains_all_queues` updated to verify that `run_once` processes all four task types (gossip, inference, provenance, temporal) before stopping.

### Changed
- Docstring and comments in `critic_agent.py` updated to reflect four task types instead of two/three.

---

## [1.35.0] - 2026-08-04

### Added
- **`resolve_temporal_conflict` tool** – resolves `temporal_conflict` tasks escalated by `TemporalStalenessSweeper` (cks‑runtime ADR‑011). Supports three actions on expired facts:
  * `bump` – extends `valid_until` by a given number of days, anchored at `max(current valid_until, now)`.
  * `archive` – marks the object as `archived` with a timestamp and clears `valid_until` (object and its relations stay in the graph).
  * `ignore` – acknowledges the conflict without any modification.
  All actions are mechanical (no LLM) and are applied via `evolve_knowledge` when `commit: true` is set.
- **`temporal_validity` extension alias** added to `EXTENSION_ALIASES` in `validate` handler so `evolve_knowledge(extensions=["temporal_validity"])` resolves correctly (constraint already existed in cks‑core ≥ 1.20.0).
- Tool count increased from 35 to 36. 14 new tests in `tests/tools/resolve_temporal_conflict/test_handler.py`.

### Changed
- `tests/test_critic_agent.py` – cleaned up unused variable in metrics test; no functional change.

---

## [1.34.0] - 2026-08-04

### Added
- **`refresh_verification` tool** – resolves `provenance_conflict` tasks escalated by `ProvenanceStalenessSweeper` (cks-runtime ADR-010). Re‑runs `verify_source` against the original URL and applies the new verification record via `evolve_knowledge` when `commit: true` is set. Fully mechanical – no LLM call, no `auto_resolve` parameter.
- **`provenance_conflict` support in `critic_agent.py`** – the Critic Agent now polls for `provenance_conflict` tasks alongside `gossip_conflict` and `inference_conflict`. Resolution calls `refresh_verification` with `commit=True`; a failing re‑verification is retried with backoff and dead‑lettered after exceeding `CKS_CRITIC_MAX_RETRIES`.
- Tool count increased from 34 to 35. New tests for `refresh_verification` handler and for the Critic Agent's provenance resolution path.

### Changed
- `tests/test_critic_agent.py` – updated mock dequeue functions to handle the new `provenance_conflict` task type in `run_once` and metrics tests.

---

## [1.33.0] - 2026-08-04

### Added
- **`resolve_gossip_conflict` tool** (ADR-006) — closes the asymmetry between inference and gossip conflict resolution by adding an LLM‑assisted arbitration path for structural merge conflicts. The tool has three modes:
  * *Interactive* — returns conflicting objects with their `target_diff`/`source_diff` and a resolution policy; the caller supplies a `resolutions` dict on the next call.
  * *Unattended* (`auto_resolve: true`) — the tool calls an LLM via the same provider dispatch as `construct_knowledge`/`arbitrate_inference_conflict` and proposes ready‑to‑use resolutions.
  * *Bypass* — the caller can always hand‑craft resolutions and call `merge_branch` directly.
- Registered in the middleware stack under `_wrap_open_session` (mirroring `merge_branch`), so both `target_session_id` and `source_session_id` are validated before the handler runs.
- 12 new unit tests in `tests/tools/resolve_gossip_conflict/test_handler.py` covering the three paths, provider dispatch (`auto`/`ollama`/`anthropic`), error handling, and already‑merged edge cases.
- Tool count increased from 33 to 34. Documentation updated in `README.md`, `docs/tools/index.md`, and `docs/tools/gossip-and-conflicts.md`.

### Changed
- ROADMAP.md — the "LLM‑assisted gossip conflict resolution" item is now marked complete (`[x]`).

---

## [1.32.2] - 2026-08-04

### Fixed
- **User‑Agent header added to all outbound HTTP requests.** `_safe_request` (used by `ingest_document`, `verify_source`, and the Enrichment Agent's `robots.txt` check) now sends `cks-mcp/1.0 (+https://github.com/Deus-corp/cks-mcp)` instead of the default `python-requests/x.y`. Several major sites — notably Wikimedia — 403 generic default user agents. Without this, every enrichment attempt against wikipedia.org (the first default adapter) failed regardless of candidate relevance.

---

## [1.32.1] - 2026-08-04

### Fixed
- **Enrichment Agent scoring: zero‑relevance candidates can now be vetoed.** The relevance component of `score_candidate` previously had a 0.3 floor, meaning a high‑authority domain (wikipedia.org, arxiv.org) could clear `CKS_ENRICHMENT_MIN_SCORE` even when it had nothing to do with the query. The floor is removed; relevance now scales from 0.0, so a candidate with no term overlap can genuinely be filtered out regardless of authority.
- **Enrichment Agent deduplication: already‑enriched URLs are skipped.** A repeat `enrichment_request` for the same object no longer re‑ingests the same source (which would fail with a duplicate identity), wasting retries and eventually dead‑lettering the task. `_already_enriched_urls` scans the session for existing `enriched_by` relations and filters candidates accordingly.
- New tests: zero‑overlap relevance regression tests for arXiv and Wikipedia, dedup behaviour when one candidate is already enriched but another is new, and `_already_enriched_urls` ignoring other relation types/objects.

---

## [1.32.0] - 2026-08-04

### Added — Critic Agent Hardening
- **Lease heartbeat for long-running resolutions** – `critic_agent` now renews its outbox lease (via the new `touch_outbox_task` in cks‑runtime 1.35.0) while a resolver runs, preventing slow `auto_resolve` LLM calls from being reclaimed by another worker. If the lease is lost, the task is abandoned without completing/failing/dead‑lettering to avoid racing with the new claimant. Configured via `CKS_CRITIC_HEARTBEAT_INTERVAL` (default 60s).
- **Circuit breaker on the LLM provider** – `LLMCircuitBreaker` opens after consecutive LLM‑attributable arbitration failures (`CKS_CRITIC_LLM_BREAKER_THRESHOLD`, default 3). While open, `auto_resolve` calls are skipped entirely for a cooldown period (`CKS_CRITIC_LLM_BREAKER_COOLDOWN`, default 60s), preventing one queued task per retry from burning LLM quota during an outage. Structural errors (e.g. `session_not_found`) never count toward the breaker. The mechanical `stale_premise_ids` path is unaffected.
- **Critic‑specific metrics** – `get_critic_metrics()` exposes processed/completed/retried/dead‑lettered counters per task type, `lease_lost`, and LLM breaker state. Wired into the existing `get_metrics` MCP tool as `critic_agent_metrics`. Process‑local (the Critic Agent runs as a separate OS process), so cross‑process observability requires future work.
- **Bugfix – mixed‑diagnostic `inference_conflict` tasks** – A payload containing both `CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT` and `CKS-EXT-STALE-PREMISE` diagnostics now resolves each via a separate `arbitrate_inference_conflict` call, instead of sending both parameter sets in one call (which the tool rejects). A payload with only stale‑premise findings is now genuinely repaired, not silently marked complete.

### Added — Enrichment Agent (external RAG / graph auto‑growth)
- **`cks‑enrichment‑agent` console script** – a new unattended agent (separate OS process, same architecture as `cks‑critic‑agent`) that polls the outbox for `enrichment_request` tasks, searches external sources, and links relevant findings back into the graph.
- **`request_enrichment` MCP tool** – enqueues an enrichment request for a given object, optionally with a custom search query. Requires a persistent storage backend (SQLite/Postgres).
- **Enrichment library** (`src/cks_mcp/enrichment/`):
  - `filters.py` – deterministic low‑value URL filtering and operator‑configured domain/prefix allow/block policy.
  - `scoring.py` – candidate scoring by domain authority + query relevance.
  - `robots.py` – `robots.txt` compliance check for unattended fetches.
  - `adapters.py` – search adapters for Wikipedia (opensearch API) and arXiv (Atom API). Adapter failures are isolated per source.
- **Agent loop** (`src/cks_mcp/agent_loop.py`) – extracted from `critic_agent.py` so all unattended agents share the same lease‑renewal (`run_resolver_with_heartbeat`) and `Resolution` type.

### Changed
- Tool count increased from 32 to 33 (`request_enrichment`). Tests updated.
- `critic_agent.py` refactored to use the shared `agent_loop` module.
- `get_metrics` schema updated to describe the new `critic_agent_metrics` field.
- ROADMAP.md updated: Critic Agent hardening backlog items marked complete; Enrichment Agent design and future agents backlog added.

---

## [1.31.1] - 2026-08-03

### Fixed
- **Critic Agent now correctly resolves `CKS-EXT-STALE-PREMISE` diagnostics** — previously a payload containing only stale-premise findings was marked complete without any repair. The agent now routes them to the mechanical `arbitrate_inference_conflict(stale_premise_ids=..., commit=True)` path, and mixed payloads (confidence conflicts + stale premises) are resolved via two independent calls instead of a single call that would be rejected as `invalid_parameter`.
- New regression tests: stale-premise-only resolution, step-level errors, mixed-diagnostic payloads handled via two separate `arbitrate_inference_conflict` calls, and partial failure in a mixed payload.

---

## [1.31.0] - 2026-08-03

### Added
- **`arbitrate_inference_conflict` now resolves `CKS-EXT-STALE-PREMISE`** via a new `stale_premise_ids` parameter. An active `InferenceStep` that still cites a since-superseded premise can now be repaired mechanically, without an LLM call, by repointing its `premises` to the current successor(s). The fix is applied through `evolve_knowledge` with `update_object` operations when `commit: true` is set.
- **`critic_agent.py` updated** to route `CKS-EXT-STALE-PREMISE` diagnostics to `stale_premise_ids` instead of dead-lettering them.
- New tests: `tests/tools/arbitrate_inference_conflict/test_handler.py` extended with 4 cases for `stale_premise_ids`.

---

## [1.30.0] - 2026-08-03

### Added
- **Critic Agent runtime loop** (`cks_mcp.critic_agent`) — the autonomous, unattended process ROADMAP.md's "Next Up" section described as the last missing piece of the Critic-agent design. Runs as its own OS process with its own `Runtime` sharing storage with the main `cks-mcp` server (same SQLite file or Postgres DSN, via `CKS_MCP_DB_PATH`), and loops: `claim_conflict_task` → resolve → `complete_conflict_task`/`fail_conflict_task`/`dead_letter_conflict_task`, for both `gossip_conflict` and `inference_conflict` task types.
  - `gossip_conflict` resolution: `merge_branch(target_session_id=<task's session>, source_session_id=<payload's source_session_id>)`. A clean merge completes the task; a structural conflict (incompatible edits to the same object) is dead-lettered rather than guessed at.
  - `inference_conflict` resolution: a single batch `arbitrate_inference_conflict(auto_resolve=True, commit=True)` call covering every `CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT` diagnostic in the task's payload. `CKS-EXT-STALE-PREMISE` findings have no arbitration primitive yet and are dead-lettered for human review.
  - A task is dead-lettered once its retry count would reach `CKS_CRITIC_MAX_RETRIES` (default 5) instead of being retried forever.
  - New console script: `cks-critic-agent` (entry point `cks_mcp.critic_agent:main_sync`).
  - Env vars: `CKS_MCP_DB_PATH` (shared storage path, defaults to the same path `cks-mcp` itself uses), `CKS_CRITIC_POLL_INTERVAL` (default 5s), `CKS_CRITIC_MAX_RETRIES` (default 5).
  - New tests: `tests/test_critic_agent.py` (16 tests, including one end-to-end test against a real SQLite-backed `Runtime` and a real `merge_branch` call, not just mocks).

---

## [1.29.0] - 2026-08-03

### Added
- **Critic-agent tool suite for the persistent outbox** — `claim_conflict_task`, `complete_conflict_task`, `fail_conflict_task`, `dead_letter_conflict_task`, `list_dead_lettered_conflicts`. These give an external Critic agent running as a genuinely *separate OS process* (its own `Runtime`, its own empty in-process `ConflictInbox`) a way to see and resolve conflicts by sharing the same SQLite/Postgres backend as the main server, using `cks-runtime` 1.34.0's new `dequeue_next_outbox_task(task_type=...)`, `dead_letter_outbox_task`, and `list_dead_letter_tasks`. `claim_conflict_task` atomically claims one `gossip_conflict`/`inference_conflict` task at a time (so two Critic-agent processes polling concurrently never claim the same one); `fail_conflict_task` reschedules with the same exponential backoff `OutboxEmbeddingWorker` uses; `dead_letter_conflict_task` permanently retires a conflict the agent couldn't resolve with confidence, visible afterwards via `list_dead_lettered_conflicts`. All five report `supported: false` under storage backends that don't implement the outbox (e.g. the default `InMemoryStorage`) instead of erroring.
- **`gossip.py`/`observability.py` dual-write into the outbox** — `GossipConflictDetected` and `InferenceConflictDetected` are now also enqueued as outbox tasks (`task_type="gossip_conflict"`/`"inference_conflict"`) whenever `runtime.storage.supports_outbox` is true, in addition to the existing write into the in-process `ConflictInbox`. This is purely additive: `list_gossip_conflicts`/`list_inference_conflicts` are unchanged and remain the same-process read path; the outbox write is what makes conflicts visible to a genuinely separate Critic-agent process, which cannot see this process's `ConflictInbox` singleton no matter what. No-ops silently (as before) under `InMemoryStorage`.
- Tool count increased from 27 to 32. New tests: `tests/tools/{claim_conflict_task,complete_conflict_task,fail_conflict_task,dead_letter_conflict_task,list_dead_lettered_conflicts}/test_handler.py`, plus dual-write coverage in `test_gossip.py` and `test_observability.py`.

### Changed
- Minimum `cks-runtime` version raised to `1.34.0` for the `task_type`-filtered `dequeue_next_outbox_task`, `dead_letter_outbox_task`, and `list_tasks_by_type`.

---

## [1.28.0] - 2026-08-03

### Added
- **`list_inference_conflicts` tool** — drains (or peeks) the queue of reasoning conflicts found by `InferenceStalenessSweeper` (ADR-009) and published as `InferenceConflictDetected` events. Each record carries `session_id`, `version_id`, and `diagnostics` (code/severity/message/location). For `CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT`, the `conclusion_id` can be extracted from the diagnostic message and passed to `arbitrate_inference_conflict` for resolution. Same peek/drain semantics as `list_gossip_conflicts`.
- **Parallel inference queue in `conflict_inbox.py`** — `ConflictInbox` now buffers `InferenceConflictDetected` events alongside gossip conflicts, with `record_inference()` / `list_inference()` methods and session-id filtering.
- **`InferenceConflictDetected` subscription in `observability.py`** — the event is always subscribed to (unlike gossip, which is opt-in), because `InferenceStalenessSweeper` is enabled by default in `cks-runtime` 1.33.0.
- New tests: `test_conflict_inbox.py` (inference queue), `test_observability.py` (subscription), and `tests/tools/list_inference_conflicts/test_handler.py`.
- Tool count increased from 26 to 27. Documentation updated: `README.md`, `docs/tools/index.md`, `docs/tools/gossip-and-conflicts.md`.

### Fixed
- `docs/tools/gossip-and-conflicts.md` — added missing `list_inference_conflicts` section and fixed broken cross-references to non-existent `reasoning.md` / `../adr/` files.
- `docs/tools/index.md` — now correctly lists 27 tools and includes `arbitrate_inference_conflict` and `list_inference_conflicts` in the Conflict Resolution group.

---

## [1.27.1] - 2026-08-03

### Fixed
- **`evolve_knowledge` no longer silently drops non-blocking diagnostics on a successful commit.** `validation.is_valid` only means no `ERROR`-severity diagnostic was raised — a `WARNING`/`INFORMATION` (e.g. `CKS-EXT-INFERENCE-CONFIDENCE-CONFLICT`, `CKS-EXT-STALE-PREMISE`) could still be present and, once the commit succeeded, was discarded instead of being returned. A caller could commit an edit that lands on top of an unresolved belief conflict and never learn about it unless they separately called `validate_knowledge`. The response now includes a `diagnostics` field (same shape as the existing failure-path diagnostics) whenever validation produced any, on every successful commit, regardless of whether `extensions` was requested; the key is omitted entirely when there are none.

---

## [1.27.0] - 2026-08-03

### Added
- **Batch mode for `arbitrate_inference_conflict`** — pass `conclusion_ids` (a list of object ids) instead of `conclusion_id` to resolve several disputed conclusions in one call. With `auto_resolve: true`, every conclusion_id still needing a decision after `winners` is resolved in **exactly one combined LLM call** (not one per conflict). `commit: true` applies the whole batch as a single `evolve_knowledge` call / version. A bad or conflict-free entry only affects its own result, never the rest of the batch.
- **`winners` parameter** — batch counterpart to `winner_id`: an object mapping each `conclusion_id` to a pre-determined winner step id (e.g. `{"obj-1": "step-a", "obj-2": "step-c"}`). Conclusions covered by `winners` are not sent to the LLM.
- **`_extract_json_array` helper** — batch-specific JSON-array extraction from LLM output, matching `extract_json` semantics but anchored on `[`/`]` instead of `{`/`}`. Handles markdown fences, trailing commentary, and truncated output.
- **`_gather_active_steps` refactored** — shared by both the single-conclusion and batch paths, so they never disagree about how a conclusion's active steps are gathered.
- **`_dispatch_llm`** — single provider-dispatch function shared by `_call_llm` and `_call_llm_batch`, so the auto/ollama/anthropic branching is implemented once.
- 16 new unit tests in `tests/tools/arbitrate_inference_conflict/test_handler.py` covering batch parameter validation, mixed conflict/no-conflict entries, caller-supplied winners, combined LLM call behaviour, error isolation between entries, and batch commit.

---

## [1.26.0] - 2026-08-03

### Added
- **`source_session_id` in `list_gossip_conflicts` records** – each conflict record now carries the `session_id` of the local branch materialized from the remote replica's content that failed to merge (via cks-runtime's `register_foreign_branch`, ADR-008 status update). A Critic agent can pass `target_session_id=session_id, source_session_id=source_session_id` straight to `merge_branch` to get back the structured per-object diff, instead of having only a bare list of conflicting ids with no way to see what the remote side actually contained. Empty when branch registration itself failed (defensive fallback) or when a record predates this field.

### Changed
- Updated `conflict_inbox.py`, `list_gossip_conflicts` handler and schema, and tests to carry and document the new field.

---

## [1.25.0] - 2026-08-02

### Added
- **`arbitrate_inference_conflict` tool** – resolves an `InferenceConfidenceConflict` (ADR-001) when two or more active `InferenceStep`s conclude the same object but disagree. Three paths to a decision:
  * *Interactive* (no extra LLM call): returns `active_steps` (ranked by entrenchment) + the arbitration `policy`, so the calling LLM client can weigh them itself and call again with `winner_id` set to its choice.
  * *Unattended* (`auto_resolve: true`): the tool calls an LLM via the same provider dispatch as `construct_knowledge` (Ollama/Anthropic/auto) to apply the policy and returns the decision.
  * *Bypass*: the caller can always apply `evolve_knowledge`'s `resolve_inference_conflict` operation directly.
- **`commit` parameter** – when supplied alongside a decision (`winner_id` or `auto_resolve`), `arbitrate_inference_conflict` applies the winning step via `evolve_knowledge` (with `resolve_inference_conflict` + `inference_confidence_conflict`/`supersession_chain` extensions) and commits a new version, instead of just returning the decision.
- New `_wrap_open_session_fields` middleware factory in `registry.py` for tools that need field validation beyond `session_id`.
- 15 new unit tests in `tests/tools/arbitrate_inference_conflict/test_handler.py` covering the three decision paths, error cases (missing session, unknown winner, invalid LLM output), and commit integration.
- Tool count increased from 25 to 26 (`tools/list` test updated).

---

## [1.24.0] - 2026-08-02

### Added
- **`list_gossip_conflicts` tool** — drains (or, with `peek: true`, previews) the queue of gossip merge conflicts a running gossip peer (`CKS_GOSSIP_ENABLED=true`) escalated via `GossipConflictDetected` (cks-runtime ADR-008) but no one has resolved yet. Previously that event was only ever logged and lost — nothing consumed it, so an external Critic agent (a separate MCP client session responsible for deciding how to resolve conflicts) had no way to discover that a background gossip cycle had failed to merge automatically. Each record carries `session_id`, `source_replica_id`, the conflicting object ids, `detected_at`, and a `record_id`; resolving one is expected to follow up with `compare_versions`/`explain_diff` for the structured diff and commit the decision through the ordinary `merge_branch` call. See `docs/tools/gossip-and-conflicts.md`.
- **`conflict_inbox.py`** — new process-level `ConflictInbox` singleton (same shape as the existing `ToolTelemetry`: lazily-created `asyncio.Lock`, capped ring buffer) that `gossip.py`'s `setup_gossip` now subscribes to `GossipConflictDetected` on the Runtime `EventBus`. Scoped to `gossip.py` rather than `observability.py`'s always-on lifecycle logging, since the event only ever fires once gossip is running.
- 13 new unit tests: `tests/test_conflict_inbox.py` (record/list, drain-by-default vs. `peek`, `session_id` filtering, eviction cap) and `tests/tools/list_gossip_conflicts/test_handler.py`; plus one new wiring test in `tests/test_gossip.py` confirming `setup_gossip` actually connects `GossipConflictDetected` to the inbox, not just that the event class exists.

### Changed
- Minimum `cks-runtime` dependency raised to `>=1.31.2` (previously `>=1.31.1`), for `GossipConflictDetected.session_id` — without it, a drained conflict record couldn't say which session it belonged to, since the event previously carried only `source_replica_id` and the conflicting object ids.

---

## [1.23.0] - 2026-08-02

### Added
- **`evolve_knowledge` now accepts `resolve_inference_conflict`** as an evolution operation (`{"type": "resolve_inference_conflict", "conclusion_id": ..., "winner_id": ...}`), wired straight through from `cks.evolution.ResolveInferenceConflict` (cks-core 1.19.0). Lets an arbiter (human or agent) that has already decided which of several competing `InferenceStep`s should stand record that decision as a single atomic evolution instead of hand-rolling `update_object` patches per losing step.
- **`evolve_knowledge` now accepts `extensions`**, mirroring `validate_knowledge`'s parameter of the same name (same `resolve_extensions`/`EXTENSION_ALIASES` resolution). Previously `evolve_knowledge`'s commit-time `cks.validate()` call only ever checked `BUILTIN_CONSTRAINTS` — an evolution that wrote `InferenceStep` fields directly (via `update_object`, or the new `resolve_inference_conflict`) had no way to also ask for `supersession_chain`/`inference_confidence_conflict`/`confidence_bounds`/etc. to be checked before commit; the only way to catch a broken supersession chain was a separate `validate_knowledge` call against the already-committed version. The response now includes `extensions_applied` when extensions were requested, matching `validate_knowledge`.
- 5 new end-to-end unit tests in `tests/tools/evolve/test_handler.py` against a real `Runtime`: `resolve_inference_conflict` supersedes the loser and leaves the winner untouched, rejects a nonexistent winner, unknown extension name is rejected, an out-of-range confidence commits silently without `extensions`, and is rejected with `CKS-EXT-CONFIDENCE-BOUNDS` when `confidence_bounds` is requested.

### Changed
- Minimum `cks-core` dependency raised to `>=1.19.0` (previously `>=1.18.0`) for `ResolveInferenceConflict`.

---

## [1.22.0] - 2026-08-02

### Added
- **Inference chain visualisation in `visualize_graph`** — new `mode: "inference"`. Instead of the structural relationship graph, the tool builds a directed reasoning graph: it walks active `InferenceStep` chains, recursively expanding premises down to base facts. Supports:
  * auto-detection of target objects (the `conclusion` of any active `InferenceStep`) when `seed_ids` is omitted;
  * `cites_step` edges (dashed) — when one inference step references another as a premise;
  * superseded-step history (`superseded_steps`) when `include_superseded: true` is set;
  * cycle protection and a configurable node budget (`max_objects`);
  * a descriptive error when the attached Core does not implement the optional `explain_inference` capability.
- **`invalid_parameter` error helper** in `cks_mcp/errors.py` — unified handling of invalid parameter values.
- 5 new unit tests in `tests/tools/visualize_graph/test_handler.py`: invalid mode, basic inference chain, `cites_step` + superseded history, node budget, unsupported core.

---

## [1.21.0] - 2026-08-02

### Added
- **`explain_knowledge` accepts an optional `object_id` parameter** — when given, answers "why is this object currently believed?" instead of the general structure-wide explanation: routes to the new `ExplainInferenceOperation` (`cks-runtime` ≥ 1.31.0), which delegates to `cks.constraints.reasoning.explain_inference` (`cks-core` ≥ 1.18.0). Recursively walks every active `InferenceStep` chain concluding the object through its premises down to base facts, plus the belief's supersession history (`superseded_steps`). Works with both call shapes `explain_knowledge` already supported — `session_id` (read-only, via the non-committing executor, same as the existing `explain` path) and the `json_data` fallback (new session + committed transaction). An attached Core that doesn't implement the optional `explain_inference` capability, or an unknown `object_id`, now surfaces as a structured `internal_error` rather than a silently empty `explanation` — unlike the general explanation, there's no meaningful empty default for "why".
- Minimum dependency versions raised to `cks-runtime>=1.31.0` and `cks-core>=1.18.0` to match.

### Tests
- 5 new unit tests in `tests/tools/explain/test_handler.py` covering the `object_id` routing: session_id path success/failure, fallback path success/failure, and confirming the no-`object_id` case still uses the plain `ExplainOperation`.

---

## [1.20.3] - 2026-08-02

### Changed
- **`extract_json()` now always validates brace balance** — even when the raw string starts with `{`, the parser checks for balanced braces and trims trailing commentary. This catches truncated LLM output (e.g. cut by `max_tokens`) and trailing prose (e.g. "Hope this helps!") early, instead of failing later with a confusing parse error.
- **`_build_llm_structure` in `ingest_document` no longer accepts an unused `runtime` parameter.** Callers updated accordingly.

### Added
- **Direct unit tests for `llm_providers`** (`tests/test_llm_providers.py`) — covers `ollama_host`, `ollama_available`, `call_ollama`, `call_anthropic`, and `extract_json` with 20+ test cases, including error paths, truncated output, and trailing commentary. No existing test exercised these functions directly before.
- **Provider-dispatch tests for `ingest_document` LLM mode** (`tests/tools/ingest_document/test_llm_dispatch.py`) — covers explicit provider selection, auto-fallback, missing provider, and parameter forwarding, mirroring the dispatch coverage that already existed for `construct_knowledge`.

---

## [1.20.2] - 2026-08-02

### Fixed
- **Duplicate assignment in `html_extract.py`** – an `itemscope` handler contained a redundant `ctx = ...` line, causing a mypy `var-annotated` error. Removed the duplicate.
- **`test_html_extract.py` had no actual tests** – the file existed but contained only `print` statements, so pytest collected zero tests. Replaced with proper test functions covering JSON-LD, microdata, OpenGraph/Twitter meta, tables, lists, sections, edge cases (empty/malformed HTML). All assertions pass.
- **Documentation typo in `ai-assisted.md`** – the LLM error response example now shows the correct `"error": "internal_error"` shape instead of `"error": "llm_call_failed"`.

### Changed
- Updated docstring of `html_extract.py` to remove "Draft/scratch" label.

---

## [1.20.1] - 2026-08-02

### Added
- **`ingest_document` now extracts structured content** — uses a new single-pass HTML parser (`html_extract.py`) to capture JSON-LD, OpenGraph/meta/Twitter tags, schema.org microdata, tables, lists, and heading-delimited sections. These are turned into CKS objects (`Section`, `Table`, `List`, `Metadata`) linked to the `Document` via `has_section`, `has_table`, `has_list`, `has_metadata` relations.
- **`ingest_document` gains optional `use_llm` parameter** — when `true`, the extracted structured content is sent to an LLM (using the same pluggable provider auto-selection as `construct_knowledge`) to build a full knowledge graph instead of the deterministic baseline. Returns the richer structure directly.
- New shared HTML parser moved to `src/cks_mcp/tools/ingest_document/html_extract.py`; tests in `tests/tools/ingest_document/test_html_extract.py`.

### Changed
- `ingest_document` now returns up to 6 object types (`Document`, `Topic`, `Section`, `Table`, `List`, `Metadata`) plus their relations, giving LLMs a far more detailed starting point for further refinement.

---

## [1.20.0] - 2026-08-02

### Added
- **Optional gossip integration (`cks_mcp/gossip.py`)** – several running `cks-mcp` instances can now automatically sync their Sessions with each other via `cks-runtime`'s existing gossip stack (ADR-008). Off by default; opt in with `CKS_GOSSIP_ENABLED=true`. New `CKS_GOSSIP_*` environment variables control host/port/peers/interval/discovery — see [Getting Started](docs/getting-started.md#gossip-syncing-sessions-across-multiple-cks-mcp-instances-optional) and [ADR-005](docs/adr/ADR-005%20Gossip%20Integration.md). Binds to `127.0.0.1` by default (not `GossipServer`'s own `0.0.0.0` default), and tracks Sessions automatically via `SessionCreated`/`SessionClosed` subscriptions rather than requiring manual bookkeeping.

### Fixed
- Depends on a `cks-runtime` fix (see that project's CHANGELOG) where `Runtime.create_session`/`create_branch`/`close_session` never actually published `SessionCreated`/`SessionClosed` on the EventBus — silently breaking both the structured lifecycle logging `observability.py` already claimed to provide and this release's gossip auto-tracking.

---

## [1.19.0] - 2026-07-31

### Added
- **`detect_contradictions` gains `inference_confidence_conflict`** – detects two or more active (non-`superseded_by`) `InferenceStep` objects that share a `conclusion` but disagree on `confidence` (see cks-core ADR-001, `cks-core>=1.16.0`). Reported at WARNING severity via the existing `contradictions` list, alongside the two existing ERROR-severity relation-pair checks.
- **`explain_diff` reports `added_inference_steps`** – added `InferenceStep` objects are now reshaped into a native reasoning summary (premises, conclusion, operator, confidence) in both `details.added_inference_steps` and the human-readable `summary`, instead of surfacing only as a generic added object.
- **`suggest_evolution` now advertises `record_inference`** – its operation-type template includes `record_inference`, so callers building a fresh operations list can find it without already knowing to look for it.

### Fixed
- **`validate_knowledge`/`detect_contradictions` couldn't resolve the ADR-001 reasoning extensions by name.** `EXTENSION_ALIASES` was never updated when cks-core shipped `inference_referential_integrity`, `confidence_bounds`, and `supersession_chain` (v1.15.2) -- every call using those names returned `unknown_extension` regardless of the structure's content. All three (plus the new `inference_confidence_conflict`) now resolve correctly.

### Changed
- Bumped `cks-core` dependency to `>=1.16.0` (adds `InferenceConfidenceConflictConstraint`; `>=1.15.2` is the actual floor `record_inference` needs, but `inference_confidence_conflict` requires 1.16.0).

---

## [1.18.1] - 2026-07-31

### Changed
- Bumped `cks-runtime` dependency to `>=1.25.1` (Postgres fixes, single version source, CI with real PostgreSQL).
- Bumped `cks-core` dependency to `>=1.15.1` (RDF/XML hardening, determinism fix, public operator properties).

---

## [1.18.0] - 2026-07-31

### Added
- **Pluggable LLM providers for `construct_knowledge`** – supports local Ollama (no API key), Anthropic API, and auto-detection (`CKS_LLM_PROVIDER` env var).
- **`fastembed` as default embedding provider** – server now prefers local, token-free embeddings via `FastEmbedEmbeddingClient`. Falls back to HuggingFace if fastembed is unavailable.

### Changed
- Bumped `cks-runtime` dependency to `>=1.25.0`.

---

## [1.17.0] - 2026-07-31

### Changed
- **Project restructuring** – every tool now lives in its own package under `src/cks_mcp/tools/<tool>/` with `handler.py` and `schema.py` (a plain Python dict, not JSON — several tools share long description text via `tools/_shared.py`, which a literal JSON file can't reference), matching the test layout. The registry module was renamed `tool_registry.py` → `registry.py` and now imports from these packages instead of defining everything inline.
- **Tests restructuring** – tests split into per-tool modules under `tests/tools/<tool>/` (one package per tool, `test_handler.py` inside), mirroring the source tree. Legacy integration tests remain at `tests/` level.
- **Comprehensive documentation** – added `docs/` with ADRs (Thin Translator, Provenance Signing, Middleware Stack, Extension Model), architecture docs (request lifecycle), protocol docs (prompts, resources), and per-category tool guides (lifecycle, branching, search-and-graph, verification, export-and-audit, ai-assisted).

---

## [1.16.1] - 2026-07-30

### Fixed
- **`telemetry.py` mypy failure** – `dashboard()`'s `error_list` was annotated `list[dict[str, int]]` while its entries mix `str` ("type") and `int` ("count") values, tripping `mypy`'s `dict-item` check. Annotation corrected to `list[dict[str, str | int]]`.
- **`get_metrics` `top_errors` reported bogus `"str"` error type** – `log_tool_call` recorded `error_type=type(error_str).__name__` for structured `{"error": "<code>"}` tool results; since `error_str` is itself a `str`, this always evaluated to the literal `"str"` instead of the actual error code (e.g. `"session_not_found"`). Now records `error_str` directly. Exception-path recording (`type(exc).__name__` for raised exceptions) was already correct and is unchanged.

### Added
- `tests/test_observability.py` – regression coverage for `log_tool_call` error-type recording (structured error dict, raised exception, success case).

---

## [1.16.0] - 2026-07-30

### Added
- **Tool telemetry dashboard** – in-memory aggregator (`ToolTelemetry`) recording per-tool call counts, success rates, p50/p95/p99 latency percentiles, and top error types. Accessible via `get_metrics` as `tool_telemetry`.
- **Composable middleware layer** – `require_fields`, `require_session`, `require_open_session`, `catch_unhandled_errors`, and `with_middleware` composition helper. All 24 tools now have structured validation stacks.
- **`get_metrics`** response extended with `tool_telemetry` dashboard alongside existing `runtime_metrics`.

### Changed
- All tool handlers in `tool_registry.py` now use `_wrap`/`_wrap_session`/`_wrap_open_session` builders instead of raw `log_tool_call()` wrapping.
- `log_tool_call` now feeds data into `tool_telemetry` in addition to stderr logging.

---

## [1.15.0] - 2026-07-30

### Added
- **`construct_knowledge` tool** — builds a Knowledge Structure from free-form text using an LLM (Anthropic API).
- **`export_session` tool** — exports a full session bundle (structure + version history) for migration or archival.
- **`structure_filters` parameter for `query_subgraph`** — post-filter extracted objects by structure fields.
- **`rename_object` operation** — now supported in `evolve_knowledge`, `suggest_evolution`, and `compare_versions`.

### Changed
- Bumped `cks-runtime` dependency to `>=1.23.1` (public operator properties, Postgres pgvector).
- Bumped `cks-core` dependency to `>=1.14.0` (`RenameObject` operator, public operator properties).

---

## [1.14.4] - 2026-07-30

### Fixed
- **BUG-04:** MCP parser now correctly handles multiple HTTP headers (e.g., `Content-Type`) between `Content-Length` and the request body, instead of failing to parse JSON.
- **BUG-02 (ingest_document):** replaced collision-prone `doc_id` truncation with a stable URL-hash-based identifier.
- **BUG-01 (embedding data loss, via cks-runtime):** SQLite `cks_object_embeddings` now uses composite primary key `(object_id, session_id)` to prevent cross-session overwrites.
- Removed unreachable dead code in `server.py` storage initialization.
- Ensured consistent use of `asyncio.to_thread` for OS-level file operations in `server.py` startup.

### Changed
- Added `filterwarnings` configuration in `pyproject.toml` to suppress spurious asyncio mark warnings on sync test methods.

---

## [1.14.3] - 2026-07-29

### Security
- **Closed provenance bypass in `serialize_knowledge` and `explain_knowledge`:** these tools now verify `VerificationRecord` signatures before persisting a session, preventing forged records from being committed. Regression tests added.
- **SSRF hardening in `ingest_document`:** replaced unsafe `requests.get` with shared `_safe_request` function (DNS pinning, manual redirect validation), matching the existing protection in `verify_source`.

### Fixed
- Removed unreachable dead code in `server.py` storage initialization.
- Ensured consistent use of `asyncio.to_thread` for OS-level file operations in `server.py` startup.

---

## [1.14.2] - 2026-07-29

### Fixed
- Console entry point (`cks-mcp` command) now correctly runs the async `main()` function via `asyncio.run()`, fixing a regression introduced in v1.14.0 that prevented the server from starting.

---

## [1.14.1] - 2026-07-29

### Fixed
- `search_semantic` now checks `supports_embedding_search` instead of `hasattr` for embedding capability detection, preventing spurious embedding client calls and misleading error messages.
- `server.py` now handles `asyncio.IncompleteReadError` gracefully, preventing crashes on truncated stdin input.

---

## [1.14.0] - 2026-07-29

### Added
- **Full async migration:** all tool handlers, `server.py` main loop, and `observability` now use `async`/`await`. The server leverages `asyncio` for non-blocking stdin reading and graceful shutdown.
- `Runtime` is now constructed via `await Runtime.create(...)`, enabling session restoration from persistent storage at startup.

### Changed
- Bumped `cks-runtime` dependency to `>=1.22.1` (async runtime, Postgres backend, `search_embeddings` fix).
- `verify_source` and `ingest_document` HTTP calls are offloaded to threads via `asyncio.to_thread`.

### Upgrade Notes
- MCP clients (Claude Desktop) do not need any changes — the JSON-RPC protocol remains identical.
- Custom test suites calling tool handlers directly must `await` them and use `pytest-asyncio`.

---

## [1.13.2] - 2026-07-29

### Changed
- Bumped `cks-runtime` dependency to `>=1.21.0` (Postgres storage backend, shared patch codec, async storage ABC).

---

## [1.13.1] - 2026-07-29

### Security
- **SSRF hardening:** `verify_source` now explicitly blocks additional non-public IP ranges (`100.64.0.0/10` — Tailscale/CGNAT shared address space, `192.0.0.0/24` — IETF protocol assignments) that Python's `ipaddress` module does not classify as private, closing a potential bypass into internal networks.

---

## [1.13.0] - 2026-07-28

### Added
- **`ingest_document` tool** — fetches a public URL, extracts title, description and keywords, and builds a Knowledge Structure with a Document object and Topic objects linked via `mentions` relations.

---

## [1.12.2] - 2026-07-28

### Changed
- `SERVER_VERSION` now derived dynamically from installed package metadata (`importlib.metadata.version`) instead of a hard-coded literal, matching `cks-runtime`'s pattern.
- Embedding client initialization failure is now logged to stderr with the underlying cause, instead of failing silently.
- `search_semantic` returns a clear message when no embedding client is configured, instead of leaking a raw `AttributeError`.
- Tool descriptions and module docstrings for `visualize_graph` and `prompts` no longer name a specific MCP client (Claude Desktop), keeping them neutral for future multi-model use.
- `ROADMAP.md` updated: removed hard-coded tool count, added `detect_contradictions` and `fork_sandbox` to completed milestones, removed `detect_contradictions` from planned v2.0 list.

---

## [1.12.1] - 2026-07-28

### Changed
- Added concrete examples of `MutualExclusionRule` and `FunctionalRelationRule` structures to `detect_contradictions` and `validate_knowledge` tool schemas, so LLMs no longer need to guess field names.
- Updated README with contradiction rule examples.

---

## [1.12.0] - 2026-07-28

### Added
- **`detect_contradictions` tool** — surfaces mutual exclusion and functional relation violations using the new contradiction constraints from cks-core.
- **`fork_sandbox` tool** — creates an isolated branch, optionally applies a hypothesis, and shows a diff from the fork point, all without affecting the parent session.

---

## [1.11.1] - 2026-07-28

### Added
- `validate_knowledge` now supports `mutual_exclusion` and `functional_relation` extensions for contradiction detection.
- Bumped `cks-runtime` dependency to `>=1.20.2` and `cks-core` to `>=1.13.0`.

---

## [1.11.0] - 2026-07-28

### Added
- `suggest_evolution` now accepts an optional `operations` parameter: when
  provided, it dry-runs those candidate operations against the session
  (the same non-committing path `evolve_knowledge` uses internally) and
  returns `would_apply`/`diagnostics`/`preview_serialized` instead of the
  template/guidance response. Lets a caller check a concrete operations
  list before spending a real `evolve_knowledge` call — and a real
  version — on a guess. Fully backward compatible: omitting `operations`
  returns the same template response as before.

---

## [1.10.6] - 2026-07-28

### Changed
- Bumped `cks-runtime` dependency to `>=1.20.1` (production stable status, `cks-core>=1.12.1` compatibility).
- Bumped `cks-core` dependency to `>=1.12.1` (fix for truncated `schema.py`).
- All three ecosystem packages now aligned on stable releases.

---

## [1.10.5] - 2026-07-28

### Changed
- Bumped `cks-runtime` dependency to `>=1.20.0` (VersionVector and fast-path merge, ADR-007 Part 2). `merge_branch` and `merge_knowledge` automatically benefit from no-op and fast-forward detection.

---

## [1.10.4] - 2026-07-28

### Changed
- Bumped `cks-runtime` dependency to `>=1.19.0` (indexed and vectorized embeddings, full mypy compliance, selective strict mode).

---

## [1.10.2] - 2026-07-27

### Changed
- Added `ruff` linting and `mypy` type checking to CI pipeline.
- Moved demo GIF to external hosting (GitHub Releases), reducing repository clone size by 6.7 MB.

---

## [1.10.1] - 2026-07-27

### Added
- `search_semantic` now supports an optional `min_score` parameter to filter results by minimum cosine similarity threshold. Results below the threshold are excluded, and an empty result set triggers a clear "nothing relevant found" message.

---

## [1.10.0] - 2026-07-27

### Added
- **`export_knowledge` tool** — export a session's Knowledge Structure to JSON-LD, Turtle, or RDF/XML, leveraging cks-core's built-in RDF/JSON-LD adapters.
- This is the 19th tool in the cks-mcp suite.

### Fixed
- `suggest_evolution` description in README and tool schema now accurately reflects its current behaviour.
- Updated MCP protocol version from `2024-11-05` to `2025-11-25`.
- Removed dead reference to non-existent `llm_client/cks_llm_client.py` from README.

---

## [1.9.3] - 2026-07-27

### Fixed
- `suggest_evolution` description in README and tool schema now accurately reflects its current behaviour (state inspection + guidance), removing promises of non-existent AI-generated operations and dry-run validation.
- Updated MCP protocol version from `2024-11-05` to `2025-11-25`.
- Removed dead reference to non-existent `llm_client/cks_llm_client.py` from README.

---

## [1.9.2] - 2026-07-27

### Fixed
- `visualize_graph` now returns `total_found_nodes`, `returned_nodes`, and `is_truncated` metadata, matching the contract of other subgraph tools.
- `max_objects` is now enforced consistently in both branches (with and without `seed_ids`), using `query_subgraph` with compact mode for all cases.
- Replaced `hasattr` duck-typing with `isinstance` for relation detection, matching the rest of the codebase.

---

## [1.9.1] - 2026-07-27

### Fixed
- `visualize_graph` now generates valid Mermaid syntax for all node IDs, including those with special characters.
- `explain_diff` now correctly distinguishes modified objects from add/remove pairs, and reports cascade-relinked relations as "relinked" rather than falsely claiming they were deleted and re-added.
- `suggest_evolution` now uses `isinstance(obj, CanonicalRelation)` instead of fragile `hasattr` duck-typing.

### Changed
- Extracted shared `field_level_diff` helper into new `cks_mcp.diffing` module, used by both merge tools and `explain_diff`.
- Extracted `TOOLS` registry into new `cks_mcp.tool_registry` module, reducing `server.py` from 929 to 322 lines.
- Added 6 functional end-to-end tests for the three new tools.

---

## [1.9.0] - 2026-07-27

### Added
- **`visualize_graph`** tool — exports a subgraph in Mermaid format for native rendering in Claude Desktop.
- **`explain_diff`** tool — produces a natural-language explanation of changes between two versions, complementing `compare_versions`.
- **`suggest_evolution`** tool — accepts a textual description of a desired change and returns a proposed list of valid evolution operators with a dry-run validation, without committing.
- 3 new tests covering the new tools' parameter validation.

### Changed
- `validate_knowledge` now supports `type_hierarchy` and `relation_type` extensions.
- Bumped `cks-runtime` to `>=1.18.2` and `cks-core` to `>=1.12.0`.

---

## [1.8.2] - 2026-07-27

### Added
- `validate_knowledge` now supports `type_hierarchy` and `relation_type` extensions, enabling ontology-based type checking and relation validation.
- Bumped `cks-runtime` to `>=1.18.2` and `cks-core` to `>=1.12.0`.

---

## [1.8.1] - 2026-07-27

### Changed
- Bumped `cks-runtime` to `>=1.18.1` (proper rollback with state restoration, DispatchRequest state mutation) and `cks-core` to `>=1.11.4` (UpdateObject export, iterative DFS, compose batching, CLI fixes, frozen metadata).

---

## [1.8.0] - 2026-07-27

### Changed
- **Breaking:** `revert_version` and `list_versions` now return the same structured `{"error": "<code>", "message": "<text>"}` shape as every other tool, instead of ad-hoc human sentences.
- `search_semantic` no longer silently swallows exceptions raised during vector search. The `not_found` response's `message` now includes the underlying error when one occurred.

### Added
- New `internal_error()` helper in `cks_mcp.errors`.
- New tests: `tests/test_revert.py` (9 tests) and `tests/test_search_semantic.py` (12 tests), including real end-to-end vector-search tests against a `SQLiteStorage`-backed `Runtime`.
- `search_semantic` now rejects an empty query immediately.
- `search_semantic` now includes a `scores` field in successful responses.

---

## [1.7.14] - 2026-07-26

### Added
- `search_semantic` now rejects an empty or whitespace-only `query` immediately with a clear `empty_query` error, instead of proceeding to (pointlessly) embed and vector-search on it.
- `search_semantic` now includes a `scores` field in successful responses when seeds were found via vector search — a dict mapping each matched seed `object_id` to its similarity score, to help debug strong vs. weak matches. Omitted when `seed_ids` were supplied explicitly, since there's no similarity score to report for those.

### Changed
- Bumped `cks-runtime` dependency to `>=1.17.7` (`search_embeddings` now returns `(object_id, similarity_score)` pairs instead of bare object IDs; `search_semantic` has been updated to consume the new return type).

---

## [1.7.13] - 2026-07-26

### Changed
- Bumped `cks-runtime` dependency to `>=1.17.5` (fixes `OutboxEmbeddingWorker` JSON payload parsing, enabling embedding generation for semantic search).

---

## [1.7.12] - 2026-07-26

### Added
- `server.py` now loads environment variables from `~/.cks-mcp/.env` at startup, ensuring `HF_TOKEN` (and any future configuration) persists across restarts and is always available to the embedding client.
- Removed old `src/cks_mcp/.env` and `src/cks_mcp/.env_example` in favour of the stable `~/.cks-mcp/` directory.

---

## [1.7.11] - 2026-07-26

### Changed
- Bumped `cks-runtime` to `>=1.17.4` (embedding dimension mismatch safety, proper `embedding_client` wiring) and `cks-core` to `>=1.11.2` (merge resolutions validation fix).

---

## [1.7.10] - 2026-07-26

### Fixed
- `search_semantic` now uses `runtime.embedding_client` (the same client instance used for indexing) instead of falling back to `StubEmbeddingClient`, restoring real semantic search functionality.

---

## [1.7.9] - 2026-07-26

### Fixed
- **Thread-safe DNS rebinding protection:** `verify_source`'s `pin_dns` context manager now uses reference-counted activation to prevent a race condition where a concurrent request could disable the DNS pinning for another in-flight request.
- **`Runtime` now properly stores and exposes `embedding_client`:** `search_semantic` was silently falling back to `StubEmbeddingClient` for query encoding, returning irrelevant results. Now uses the same client configured for indexing.
- **Embedding dimension mismatch detection:** `search_embeddings` now safely skips stored embeddings whose dimension differs from the query, instead of silently computing garbage similarity scores.
- **`KnowledgeStructure.merge()` contract fix:** a `resolutions` entry for an id that both branches touched but converged on the same value is now correctly rejected with `ValueError`, as documented.
- **Stable data directory:** provenance secret and SQLite database are now stored under `~/.cks-mcp` (overridable via `CKS_MCP_DATA_DIR`), so server restarts from different working directories no longer lose previously signed verifications or create empty databases.

---

## [1.7.8] - 2026-07-26

### Fixed
- **Critical provenance bypass:** `verify_structure_provenance` now identifies `verified_by` relations structurally (via `structure.relations()`), not by the caller-chosen `identity.type` string. Previously, a forged `VerificationRecord` linked by a relation with any `identity.type` other than the literal string `"Relation"` was invisible to the signature check and could be committed as a valid version.
- Added 2 regression tests confirming forged records are rejected and genuine records are accepted regardless of `identity.type`.
- Bumped `cks-runtime` to `>=1.17.3` and `cks-core` to `>=1.11.1`.

---

## [1.7.7] - 2026-07-26

### Fixed
- `evolve_knowledge` and `merge_branch` probe calls are now unmetered, so `get_metrics` no longer reports double the actual number of tool invocations.

### Added
- `merge_branch` conflict responses now include a `field_level_auto_merge_note` when the ADR-007 fast path was unavailable, explaining why the conflict wasn't auto-resolved.

---

## [1.7.6] - 2026-07-26

### Changed
- Bumped `cks-runtime` dependency to `>=1.17.0` (adds field-level auto-merge for disjoint edits, ADR-007 Part 2). `merge_branch` and `merge_knowledge` automatically benefit from the new auto-resolution logic.

---

## [1.7.5] - 2026-07-26

### Changed
- Bumped `cks-runtime` dependency to `>=1.16.0` (adds operation log for field-level change tracking, ADR-007 Part 1).

---

## [1.7.4] - 2026-07-25

### Changed
- Updated `search_semantic` tool description to reflect that vector search is live and `seed_ids` is optional.
- `merge_knowledge` now reports `dropped_relations` in its response when referential integrity causes relations to be excluded.
- Bumped `cks-runtime` to `>=1.15.0` and `cks-core` to `>=1.11.0`.

### Fixed
- `merge_knowledge` no longer silently drops relations without informing the caller.

---

## [1.7.3] - 2026-07-25

### Added
- 7 new tests for `merge_knowledge` covering conflicts, resolutions (branch_a, branch_b, custom object, malformed, partial).
- 5 new tests for `merge_branch` with resolutions.
- Bumped `cks-runtime` dependency to `>=1.14.0`.

### Fixed
- `_parse_resolutions` now correctly handles raw JSON object definitions for custom resolutions in both merge tools.

---

## [1.7.2] - 2026-07-25

### Added
- `merge_branch` and `merge_knowledge` now accept raw JSON object definitions in the `resolutions` parameter, enabling custom synthesized conflict resolutions without pre-constructing KnowledgeObjects.
- 5 new tests covering all `resolutions` scenarios (branch_a, branch_b, custom object, partial, malformed).

### Changed
- Updated `merge_branch` conflict message to recommend using the `resolutions` parameter for a one-shot resolution.

---

## [1.7.1] - 2026-07-25

### Added
- `merge_branch` now accepts optional `resolutions` parameter, enabling partial merges with per-object conflict resolution strategies.
- Updated tool schema to document `resolutions` for `merge_branch`.

### Changed
- Improved default description for GPU in knowledge graph examples to enhance semantic search relevance.

---

## [1.7.0] - 2026-07-25

### Added
- `merge_knowledge` and `merge_branch` now accept an optional `resolutions` parameter for partial three-way merges, allowing callers to specify per-object conflict resolution strategies (`"branch_a"`, `"branch_b"`, `null`, or a custom object definition).
- Updated tool schema in `server.py` to document the `resolutions` parameter for both merge tools.
- Bumped `cks-runtime` dependency to `>=1.13.0` (adds `resolutions` support in `CoreBridge.merge()` and `MergeOperation`).

### Changed
- `search_semantic` now correctly triggers vector search when `seed_ids` is omitted or empty, instead of requiring explicit IDs. The parameter is no longer listed as required.

---

## [1.6.19] - 2026-07-24

### Fixed
- `validate_knowledge` now retrieves the correct (most recent) failed operation result when recovering diagnostics from a `RuntimeError`, ensuring detailed error messages are returned instead of a generic "Validation failed".
- Bumped `cks-runtime` to `>=1.11.0` (automatic `parent_version_id` for branches, improved diagnostics recording).

---

## [1.6.18] - 2026-07-24

### Fixed
- **Inconsistent error handling in `validate_knowledge`:** validation failures during commit (e.g., dangling references) now return structured diagnostics instead of a raw `RuntimeError` traceback.
- **`merge_knowledge` now returns structured diffs** for conflicts (`target_diff`/`source_diff`), matching `merge_branch`'s behavior instead of leaking Python `repr()` strings.
- **Updated `merge_branch` documentation** to reflect actual field names (`target_diff`/`source_diff` instead of `base_state`/`target_state`/`source_state`).

---

## [1.6.17] - 2026-07-24

### Changed
- Bumped `cks-runtime` dependency to `>=1.10.3` (fixes OutboxEmbeddingWorker crash, restoring semantic embedding generation and enabling `search_semantic` without explicit `seed_ids`).

---

## [1.6.16] - 2026-07-24

### Changed
- `search_semantic` now normalizes query vectors, improving semantic search accuracy when combined with normalized embeddings from `cks-runtime>=1.10.2`.
- Bumped `cks-runtime` dependency to `>=1.10.2`.

---

## [1.6.14] - 2026-07-24

### Changed
- Bumped `cks-runtime` to `>=1.10.0` — includes the new generalised Task Bus, enabling future background task types like conflict escalation.

---

## [1.6.13] - 2026-07-24

### Added
- `query_subgraph` now supports `compact_mode`. When set to `true`, the response contains arrays of `nodes` and `edges` instead of full canonical JSON, making the output significantly smaller and easier for LLMs to process.

---

## [1.6.12] - 2026-07-24

### Changed
- Merge conflict responses now include a human-readable `target_diff` and `source_diff` per conflict, instead of opaque `str()` dumps. This makes it easier for LLMs and users to understand what changed in each branch.
- Bumped `cks-runtime` to `>=1.9.5` (restores version history for persistent sessions).

---

## [1.6.11] - 2026-07-24

### Fixed
- **Provenance signing secret now persists across server restarts.** If `CKS_MCP_SECRET` is not set, the server generates a random secret on first launch and saves it to `data/.cks_provenance_secret`. Previously verified `VerificationRecord` objects remain valid after restart.

---

## [1.6.10] - 2026-07-24

### Fixed
- **`evolve_knowledge` now validates the evolved structure before committing.** If the evolution would produce an invalid structure (e.g., dangling references from a misused `remove_relation`), the commit is blocked with a clear error, preventing corrupted data from entering the session history.
- Bumped `cks-runtime` to `>=1.9.4` (fixes embedding worker for delta versions).

---

## [1.6.9] - 2026-07-24

### Fixed
- `search_semantic` now filters out `Relation` type objects from the vector search results, ensuring that only domain objects (Concepts, Documents, etc.) are returned as seeds.

---

## [1.6.8] - 2026-07-24

### Changed
- Bumped `cks-runtime` to `>=1.9.3` — embedding worker now excludes relation objects, so `search_semantic` no longer returns false positives like relation IDs.

---

## [1.6.7] - 2026-07-24

### Changed
- Bumped `cks-runtime` to `>=1.9.2` (updated HuggingFace API endpoint).

---

## [1.6.6] - 2026-07-24

### Fixed
- Global `socket.getaddrinfo` monkey-patch replaced with temporary thread-local override, restoring DNS resolution for non-verification HTTP requests (e.g., Hugging Face API).

---

## [1.6.5] - 2026-07-24

### Changed
- Switched to `HuggingFaceEmbeddingClient` for free, token-based semantic embeddings via Hugging Face Inference API. Requires `HF_TOKEN` environment variable.
- Bumped `cks-runtime` dependency to `>=1.9.1`.

---

## [1.6.4] - 2026-07-23

### Added
- Server now initializes `OpenAIEmbeddingClient` at startup, enabling real semantic embeddings for `search_semantic`. Falls back gracefully if `OPENAI_API_KEY` is not set or `openai` package is missing.

---

## [1.6.3] - 2026-07-23

### Changed
- `search_semantic` now uses the runtime's configured `EmbeddingClient` for query vectorization, enabling real semantic search when a real client is configured.
- Bumped `cks-runtime` dependency to `>=1.9.0`.

---

## [1.6.2] - 2026-07-23

### Fixed
- `search_semantic` now correctly triggers vector search when `seed_ids` is omitted or empty, instead of requiring explicit IDs. The parameter is no longer listed as required.

---

## [1.6.1] - 2026-07-23

### Changed
- Bumped `cks-runtime` dependency to `>=1.8.2` (fixes session association for embeddings; `search_semantic` now works without explicit seed_ids).

---

## [1.6.0] - 2026-07-23

### Changed
- `search_semantic` now uses vector embeddings for ANN search instead of requiring explicit `seed_ids`. Falls back gracefully if embeddings are unavailable.
- Bumped `cks-runtime` dependency to `>=1.8.1`.

---

## [1.5.4] - 2026-07-23

### Fixed
- **Content-Length parsing:** body is now read as bytes and decoded, fixing request corruption with multi-byte UTF-8 characters.
- **Off-by-one errors in `resources.py`:** `read_resource` now correctly resolves session, version-list, and specific-version URIs.

### Added
- `get_metrics` tool is now registered and exposed to clients.

---

## [1.5.3] - 2026-07-23

### Fixed
- Registered `get_metrics` tool in `server.py` — it was implemented but not exposed to clients, so LLMs couldn't discover it.

---

## [1.5.2] - 2026-07-23

### Added
- `get_metrics` tool — returns runtime metrics (invocation counts and average execution times per operation type).
- Bumped `cks-runtime` dependency to `>=1.6.2`.

---

## [1.5.1] - 2026-07-23

### Changed
- Bumped `cks-runtime` dependency to `>=1.6.1` (fixes a critical bug where `Dispatcher.dispatch()` was not instantiating operations correctly, causing crashes for any `DispatchRequest`-based transactions).

---

## [1.5.0] - 2026-07-23

### Added
- `search_semantic` tool — performs semantic search over a session's Knowledge Structure. Accepts a natural language query and seed IDs, then expands the neighbourhood using `query_subgraph`. This is the first step towards a full vector-index-powered RAG pipeline.

---

## [1.4.1] - 2026-07-23

### Added
- `evolve_knowledge` now returns an optional `cascade_removed_relations` field, listing relation IDs that were silently deleted because a referenced object was removed. This makes cascade side effects explicit and auditable.

---

## [1.4.0] - 2026-07-23

### Added
- **MCP Prompts:** the server now offers ready‑to‑use prompt templates (`create_knowledge_graph`, `verify_claim`, `explore_subgraph`, `branch_and_merge`) via `prompts/list` and `prompts/get`. Users can select a workflow from Claude Desktop's prompt menu and fill in parameters without knowing the tool names or JSON syntax.
- New module `prompts.py` implementing the prompt handlers.

---

## [1.3.5] - 2026-07-23

### Fixed
- **Session leak on provenance rejection:** `validate_knowledge` and `evolve_knowledge` (without `session_id`) no longer create and persist a session before checking provenance. A structure with a forged or missing `VerificationRecord` signature is fully rejected — no `session_id` is returned, and no session is registered in the runtime. Previously, the session was persisted immediately, making the forged content readable via `serialize_knowledge`, `explain_knowledge`, `query_subgraph`, and MCP Resources.
- **Severity-blind blocking:** `evolve_knowledge`, `merge_knowledge`, and `merge_branch` now block only on `error`-severity provenance diagnostics (forged/ambiguous signatures). `warning`-severity diagnostics (e.g. a genuinely-signed but as-yet-unlinked `VerificationRecord`) no longer prevent a legitimate commit, restoring the two-step workflow of adding a signed record and linking it in separate operations.
- **Truthiness bug in `merge_branch`:** `if probe.payload` replaced with `if probe.payload is not None` to avoid skipping provenance check on empty but valid merged structures.
- Updated regression tests to cover session leak, severity-aware blocking, and false-positive unlinked-record scenario (50/50 tests passing).

---

## [1.3.4] - 2026-07-23

### Changed
- Bumped `cks-runtime` dependency to `>=1.6.0`. Sessions and versions now persist across server restarts, fully restoring the operational state when Claude Desktop reconnects or the server process is restarted.

### Fixed
- After a server restart, all previously created sessions are now immediately available via `get_session()`, `list_sessions`, and the MCP Resources surface. No data is lost.

---

## [1.3.3] - 2026-07-22

### Fixed
- **Remaining provenance bypass in `validate_knowledge`:** the provenance-signature gate added in 1.2.6 covered `evolve_knowledge` and `merge_knowledge`/`merge_branch`, but not `validate_knowledge` itself -- which is the tool that actually creates a session's first committed version. It previously committed unconditionally and only checked `VerificationRecord` signatures afterward to set the response's `valid` field, so a forged record still ended up as a real, persisted version regardless of `valid: false` -- visible to `serialize_knowledge`, `explain_knowledge`, `query_subgraph`, and the MCP Resources surface with no indication it had failed a check. `validate_knowledge` now verifies provenance before deciding whether to commit at all, mirroring the existing dry-run-then-commit pattern; a structure with a forged or missing signature is validated (all core-level diagnostics still returned) but never committed, and the response omits `version_id` entirely rather than returning one for a version that doesn't exist.
- 5 new regression tests covering the forged-signature, missing-signature, genuine-signature, re-validation-of-an-existing-session, and no-VerificationRecord-present cases.

---

## [1.3.2] - 2026-07-22

### Added
- **Demo GIF** showing a complete CKS workflow from a single sentence ("Use cks-mcp to create a knowledge graph about the water cycle…"), including validation and explanation, all within Claude Desktop.
- Simplified **Quick Start** section explaining that CKS is just a conversation — no programming, no command line.

### Changed
- Updated README with demo GIF, streamlined installation instructions, and a new `query_subgraph` usage example.

---

## [1.3.1] - 2026-07-22

### Fixed
- Added `"resources": {}` to the server's `initialize` capabilities, enabling clients to discover MCP Resources.

---

## [1.3.0] - 2026-07-22

### Added
- **MCP Resources:** the server now exposes active sessions, their version histories, and each version's Knowledge Structure as virtual resources (`cks://sessions/...`). LLMs can read them directly without calling tools, making the knowledge graph instantly browsable.
- New module `resources.py` implementing `resources/list` and `resources/read` handlers.

---

## [1.2.6] - 2026-07-22

### Fixed
- **Critical provenance bypass:** `evolve_knowledge` and `merge_branch`/`merge_knowledge` now verify `VerificationRecord` signatures before committing new state. Previously, a hand‑written record with a fake signature could be inserted via evolution or merging, circumventing the check that `validate_knowledge` applies. This restores the invariant that only genuinely verified sources can appear as `VerificationRecord` objects in any session history.
- Extracted `verify_structure_provenance` into `provenance.py` as a shared helper, used by all tools that modify knowledge state.

---

## [1.2.5] - 2026-07-22

### Fixed
- Server now automatically falls back to a writable temporary directory (or in‑memory storage) when the default `data/` directory is read‑only, such as in Claude Desktop's sandboxed environment. This prevents `OSError: [Errno 30] Read-only file system` crashes.

---

## [1.2.4] - 2026-07-22

### Fixed
- Server now explicitly creates the `data/` directory for SQLite storage on startup, preventing crashes when Claude Desktop launches the server in a clean environment.
- Improved error logging during server initialization.

---

## [1.2.3] - 2026-07-22

### Changed
- Enabled persistent SQLite storage by default (`cks_mcp.db`), using `cks-runtime>=1.5.1`. Sessions and versions now survive server restarts.
- Bumped `cks-runtime` dependency to `>=1.5.1`.

---

## [1.2.2] - 2026-07-22

### Added
- Structured JSON logging for every tool invocation (written to stderr), recording tool name, session_id, duration_ms, and success/error.
- Subscription to Runtime lifecycle events (`SessionCreated`, `TransactionCommitted`, `VersionCreated`, `ValidationFailed`, etc.) — all events are logged as JSON lines, providing a full operational audit trail.

---

## [1.2.1] - 2026-07-22

### Changed
- Bumped `cks-runtime` dependency to `>=1.4.1` and `cks-core` to `>=1.9.1` (includes query_subgraph ordering and relation-as-seed fixes).

---

## [1.2.0] - 2026-07-22

### Added
- `query_subgraph` tool – extracts a k‑hop neighbourhood from a session's Knowledge Structure as a self‑contained subgraph, with optional relation/object type filters and a token/object budget that ranks candidates by degree, type weight, and distance. Returns full truncation metadata (`total_found_nodes`, `returned_nodes`, `is_truncated`, `truncation_reason`, `suggested_next_seed`) so an LLM agent always knows whether the neighbourhood was truncated and can resume from the suggested next seed.
- Bumped `cks-runtime` dependency to `>=1.4.0` and `cks-core` to `>=1.9.0`.

---

## [1.1.1] - 2026-07-22

### Fixed
- `explain_knowledge` with `session_id` no longer creates a new empty version in the session's history. Read-only explanations now bypass the transaction pipeline and use the executor directly, preventing version history pollution. (#bug 1)
- Bumped `cks-runtime` dependency to `>=1.3.2` and `cks-core` to `>=1.8.3`.

---

## [1.1.0] - 2026-07-21

### Added
- `create_branch` tool — fork a new session from an existing one, optionally from a specific historical version, for isolated experimentation without touching the parent session.
- `merge_branch` tool — session-aware three-way merge between a target session and a branch session. Unlike `merge_knowledge`, the merge base is resolved automatically from the branch's recorded fork point; on success the merged result is committed as a new version of the target session, on conflict a structured `conflicts` list (`object_id`, `base_state`, `target_state`, `source_state`) is returned instead, with guidance not to retry `merge_branch` unchanged but to resolve conflicts via `evolve_knowledge`.
- `close_session` tool — closes a session, intended for releasing a branch session once `merge_branch` has integrated it.
- Bumped `cks-runtime` dependency to `>=1.3.0` for `Runtime.create_branch`, `CoreBridge.merge`/`supports_merge`, and `MergeOperation`.

---

## [1.0.10] - 2026-07-21

### Fixed
- `merge_knowledge` now correctly returns detailed conflict information (object_id, base, branch_a, branch_b) when a `MergeConflictError` occurs, using duck-typing instead of fragile class name checks.

---

## [1.0.9] - 2026-07-21

### Fixed
- `merge_knowledge` tool now correctly handles `MergeConflictError` without relying on direct imports.

---

## [1.0.8] - 2026-07-21

### Changed
- Bumped `cks-runtime` to `>=1.2.3` and `cks-core` to `>=1.8.2` for merge support.
- `merge_knowledge` tool – three-way merge of Knowledge Structures with conflict detection.

---

## [1.0.7] - 2026-07-21

### Changed
- Bumped `cks-runtime` dependency to `>=1.2.2` for full compatibility with delta version storage and performance improvements from `cks-core` v1.8.0.

---

## [1.0.6] - 2026-07-21

### Changed
- `compare_versions` now uses `session.get_version_state()` to reconstruct base versions, compatible with `cks-runtime` v1.2.0's delta version storage.

---

## [1.0.5] - 2026-07-20

### Fixed
- Server no longer crashes with an unhandled `ValueError` when a client sends a malformed `Content-Length` header. The error is now caught and returned as a proper JSON-RPC parse error, keeping the server alive for subsequent requests.

---

## [1.0.4] - 2026-07-20

### Fixed
- `compare_versions` no longer crashes with "Object of type RemoveRelation is not JSON serializable" when the diff contains relation removals. The serialiser now correctly handles all four operator types.

---

## [1.0.3] - 2026-07-20

### Fixed
- `compare_versions` now correctly computes the diff from `base_version` to `current`, and returns explicit `direction`, `base_version_id`, `current_version_id`, and a semantic `summary` (counts of added/removed objects and relations). This makes the diff direction unambiguous for LLMs.
- `ValidateOperation` now correctly returns `FAILED` status when the structure is invalid, preventing invalid structures from being committed as versions.
- `TransactionManager._finish` now removes completed transactions from the registry, preventing memory leaks.
- `Dispatcher.dispatch` no longer writes to the non-existent `context.diagnostics`.
- `CoreBridge.validate` now passes `extra_constraints` even when empty (`is not None` check).

### Added
- Integration tests for `compare_versions` direction and `TransactionManager` cleanup (2 new tests, total 30 passed).

---

## [1.0.2] - 2026-07-20

### Changed
- `compare_versions` now returns explicit `direction`, `base_version_id`, `current_version_id`, and a semantic `summary` (counts of added/removed objects and relations), making the diff direction unambiguous for LLMs.
- Updated tool description in `server.py` to document the new response format.

---

## [1.0.1] - 2026-07-20

### Added
- `compare_versions` tool: computes the structural diff between the current state of a session and a specified target version, returning a compact list of changes.
- Session-aware `serialize_knowledge`, `explain_knowledge`, and `evolve_knowledge` — all tools now accept an optional `session_id` to operate on existing sessions.
- Stable provenance secret via `CKS_MCP_SECRET` env var.

### Changed
- `verify_source` now uses deterministic, IPv4-first IP selection with automatic fallback.
- `VerificationRecord` shape and provenance checks are now unconditional, regardless of the `verification_record` extension parameter.
- Improved error responses for LLM readability.

---

## [1.0.0] - 2026-07-19

### Added
- First stable release of the CKS MCP Server.
- Unconditional verification of `VerificationRecord` shape and provenance, regardless of whether the `verification_record` extension is explicitly requested.
- Deterministic, IPv4-first IP candidate selection in `verify_source` with automatic fallback to additional resolved addresses.
- Updated tests covering the new IP resolution contract and fallback behaviour (32 tests total).

---

## [0.7.8] - 2026-07-19

### Fixed
- `list_versions` now builds version history directly from the session instead of delegating to the OperationExecutor, fixing the persistent error that prevented LLMs from inspecting session history.

---

## [0.7.7] - 2026-07-19

### Added
- **Session-aware tools:** `validate_knowledge`, `serialize_knowledge`, `explain_knowledge`, and `evolve_knowledge` now accept an optional `session_id` parameter to operate on an existing session instead of creating a new one. This enables predictable, multi-step workflows within a single session.
- `revert_version` now returns the `serialized` canonical JSON of the reverted state, eliminating the need for a separate `serialize_knowledge` call to verify the result.
- **Production-ready provenance:** The signing secret can now be configured via the `CKS_MCP_SECRET` environment variable (supports raw strings, hex, and base64), making provenance verification stable across server restarts.
- Improved error handling in `list_versions`.

### Changed
- `evolve_knowledge` no longer requires `json_data` when `session_id` is provided, reducing unnecessary re-parsing of large structures.
- Provenance checks now distinguish between ambiguous, unlinked, and unverified records for clearer diagnostics.

---

## [0.7.6] - 2026-07-19

### Fixed
- `list_versions` now handles internal errors gracefully and returns an empty list when no versions exist, instead of failing silently.

---

## [0.7.5] - 2026-07-19

### Added
- `evolve_knowledge` now accepts an optional `session_id` parameter. When provided, the evolution is applied to the existing session, adding a new version to its history. This enables predictable version tracking within a single session.

---

## [0.7.4] - 2026-07-19

### Changed
- Improved tool descriptions for `validate_knowledge`, `evolve_knowledge`, `list_versions`, and `revert_version` to explicitly document the session and versioning workflow, helping LLMs discover the correct usage pattern without trial and error.

---

## [0.7.3] - 2026-07-19

### Fixed
- `list_versions` and `revert_version` now require an explicit `session_id` parameter, eliminating unpredictable behaviour when multiple sessions exist. Tools always return the `session_id` they operated on.

---

## [0.7.2] - 2026-07-19

### Fixed
- Response format now matches the incoming request: `Content-Length`-framed for clients that use headers, plain line-delimited for legacy clients. This restores full compatibility with Claude Desktop and other MCP clients.

---

## [0.7.1] - 2026-07-19

### Fixed
- Server now supports both `Content-Length`‑framed and plain line‑delimited modes, restoring compatibility with Claude Desktop and other MCP clients that do not use headers.

---

## [0.7.0] - 2026-07-19

### Added
- `list_versions` and `revert_version` tools, giving LLMs the ability to inspect the version history of a session and safely roll back to any previous state. Powered by `cks-runtime`'s new `ListVersionsOperation` and `RevertVersionOperation`.

---

## [0.6.3] - 2026-07-19

### Fixed
- **HTTPS/SNI fix in `verify_source`**: Replaced custom HTTPAdapter with thread-local `socket.getaddrinfo` override, preserving SNI and SSL certificate validation while still preventing DNS rebinding.
- **MCP protocol compliance**: Implemented `Content-Length` header-based message framing, fixing potential JSON parsing errors for large or formatted requests.
- **LLM-friendly errors**: Business errors are now returned as successful tool responses with `isError: true`, allowing LLMs to read and recover from errors instead of treating them as server crashes.

---

## [0.6.2] - 2026-07-19

### Fixed
- Provenance check is now unconditional for any `VerificationRecord`, closing a bypass where an LLM could skip validation by omitting the extension parameter.
- DNS rebinding SSRF vector closed by pinning HTTP connections to the specific IP address resolved during the safety check.

---

## [0.6.1] - 2026-07-19

### Fixed
- Restored standard MCP protocol version (`2024-11-05`) that was accidentally overwritten, which prevented Claude Desktop from connecting.

---

## [0.6.0] - 2026-07-19

### Added
- Provenance signing for `VerificationRecord` – only records produced by `verify_source` pass the new `CKS-MCP-UNVERIFIED-PROVENANCE` check.
- SSRF protection in `verify_source` – URLs are validated against public-IP allowlist.
- Unique IDs (uuid4) for all objects created by `verify_source`.
- Tests for SSRF protection, unique IDs, and provenance signing (7 new tests, total 24 passed).

### Changed
- All tools now catch `cks.SerializationError` and return structured error messages instead of raw tracebacks.
- `invalid_json_error` now accepts a `details` parameter.

---

## [0.5.2] - 2026-07-19

### Changed
- Improved error responses in MCP server: structured error messages with types (`invalid_json`, `validation_failed`) now replace raw tracebacks, helping LLMs understand what went wrong and how to recover.
- Updated server version string to 0.5.2 and imported new error helpers from `cks_mcp.errors`.

---

## [0.5.1] - 2026-07-19

### Changed
- `serialize_knowledge` and `explain_knowledge` tools now read operation results directly from the transaction's `results` field instead of calling `CoreBridge` a second time. This eliminates redundant semantic computations and keeps all operation payloads in one place.

---

## [0.5.0] - 2026-07-19

### Added
- New `verify_source` tool. It performs an actual HTTP request to check a source's availability and creates a `VerificationRecord` object. This ensures that verification records can only be produced by real checks, not fabricated by the model.

---

## [0.4.4] - 2026-07-19

### Added
- `verification_record` extension now available in `validate_knowledge`'s `extensions` parameter. This extension checks the integrity of `VerificationRecord` objects, ensuring they have exactly one `verified_by` relation, a valid timestamp, a recognized check method, and no qualitative judgment fields.
- Updated tool descriptions with an example of a correct `VerificationRecord`.

---

## [0.4.3] - 2026-07-19

### Changed
- Added a complete worked example of a correct `EmbeddingProjection` with its `represents` relation to the description of the `extensions` parameter in `validate_knowledge`. This further reduces trial-and-error by giving the model a template to follow.

---

## [0.4.2] - 2026-07-19

### Changed
- Improved tool descriptions: `json_data` now includes a full worked example of a CKS Knowledge Structure, and `operations` in `evolve_knowledge` includes per‑operator field requirements and an example. This dramatically reduces the number of trial‑and‑error round‑trips a cold LLM needs to construct valid requests (measured: from 3 to 0).

---

## [0.4.1] - 2026-07-18

### Added
- Restored and expanded subprocess integration tests (`test_integration.py`) covering real stdin/stdout transport, including the new `extensions` parameter (3 new tests, total 19 passed).

---

## [0.4.0] - 2026-07-18

### Added
- `validate_knowledge` now supports an optional `extensions` parameter (list of human-readable names like `"embedding_projection"`) to opt into additional validation rules for a single call.
- Structured error response for unknown extension names instead of a raw traceback.
- Integration tests for the extensions feature with real Runtime + CksCoreAdapter (5 new tests, total 17 passed).

### Changed
- Updated `validate_knowledge` tool description in MCP server schema to document the `extensions` parameter.

---

## [0.3.3] - 2026-07-18

### Removed
- Deleted obsolete `src/cks_mcp/tools.py` – an outdated copy of test utilities that survived four releases.

---

## [0.3.2] - 2026-07-18

### Fixed
- `validate_knowledge` now correctly returns `"valid": false` with structured diagnostics when a Knowledge Structure is invalid, instead of crashing or hardcoding `true`. It reads diagnostics from the session after the validation transaction (bugs #1, #2).
- Updated tests to cover both valid and invalid structure scenarios.

---

## [0.3.1] - 2026-07-18

### Fixed
- `evolve_knowledge` now uses `cks.evolution.parse_operations` to convert JSON operation descriptors into proper `StructuralOperator` objects, fixing the `AttributeError: 'dict' object has no attribute 'apply'` crash.
- Requires `cks-runtime>=0.4.4` and `cks-core>=1.2.1`.
- Added missing `EvolveOperation` import in `evolve_knowledge` tool.

### Changed
- Updated tests to use valid JSON operation descriptors for evolve.

---

## [0.3.0] - 2026-07-18

### Changed
- Tools now use the full `create_session` → `begin_transaction` → `commit_transaction` cycle from `cks-runtime`. Every call produces an immutable Version and collects Diagnostics.
- Requires `cks-runtime>=0.4.2` and `cks-core>=1.2.0`.
- Responses now include `version_id` and `session_id` for traceability.

### Fixed
- `test_server.py` now uses serializable mocks for session and version, eliminating `Object of type MagicMock is not JSON serializable` errors.

### Updated
- README reflects transactional tool behaviour and new response fields.

---

## [0.2.1] - 2026-07-18

### Changed
- Improved tool responses for better LLM readability.
  - `validate_knowledge` now returns `error_count`, `warning_count`, `information_count` and a human‑readable message.
  - `explain_knowledge` now returns `object_count`, `relation_count` and a summary.
  - `evolve_knowledge` returns `serialized` result and `operations_applied` count.
- Updated tests to verify new response fields (11 passing).

---

## [0.2.0] - 2026-07-18

### Added
- Working MCP server with four tools: `validate_knowledge`, `serialize_knowledge`, `explain_knowledge`, `evolve_knowledge`.
- LLM client (`llm_client/cks_llm_client.py`) supporting Groq, DeepSeek, and local llama_cpp models.
- `.env` support via `python-dotenv`.
- Unit tests for server and tools (9 passing).

### Changed
- Tools now use direct `CoreBridge` calls instead of sessions/transactions (avoids serialization issues).
- Server reads JSON-RPC requests line-by-line from stdin and writes responses to stdout.

### Fixed
- `cannot pickle 'mappingproxy' object` error resolved by using `CoreBridge` directly.
- Valid Knowledge Structure JSON examples added to tests.

---

## [0.1.1] - 2026-07-15

### Fixed

- CI/CD publish workflow trigger.

---

## [0.1.0] - 2026-07-15

### Added

- Initial MCP server implementation with JSON-RPC over stdio.
- `validate_knowledge` tool.
- `query_relations` tool.
- `compare_structures` tool.
- `evolve_knowledge` tool.
- `derive_knowledge` tool.
- CI/CD pipeline (GitHub Actions).