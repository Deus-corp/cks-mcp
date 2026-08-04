# Roadmap

This roadmap outlines the planned evolution of the CKS MCP Server.
It reflects the current state of the project and charts the course
towards a stable, production-ready platform and beyond.

---

# Current Status (v1.28.x — August 2026)

The project has matured into a robust platform. It provides LLMs with
a verifiable, persistent knowledge backbone, semantic search, and a full suite of tools for knowledge lifecycle management (see
[README](README.md#available-tools) for the current list).

## ✅ Completed Milestones

### Core Server & Protocol
- Full MCP protocol compliance (`initialize`, `tools/list`, `tools/call`, `ping`).
- MCP Resources and Prompts for seamless UI integration.
- JSON-RPC over stdio with structured, LLM-friendly error responses.
- **CI/CD:** `ruff` linting and `mypy` type checking run on every push.

### Canonical Tools
- **Knowledge Lifecycle:** `validate_knowledge`, `evolve_knowledge`, `serialize_knowledge`, `explain_knowledge`.
- **Version Control:** `list_versions`, `compare_versions`, `revert_version`.
- **Branching & Merging:** `create_branch`, `merge_branch`, `merge_knowledge`, `close_session`, `fork_sandbox`.
- **Graph Exploration:** `query_subgraph` (with compact mode and budget), `search_semantic` (real embeddings via HuggingFace/fastembed, with `min_score` threshold and similarity scores).
- **Audit & Metrics:** `get_metrics` for runtime statistics.
- **Visualization & Diff:** `visualize_graph` (Mermaid export, structure and inference modes), `explain_diff` (natural-language change summaries).
- **AI Assistance:** `suggest_evolution` (state inspection + guidance for building operations — no LLM call required), `construct_knowledge` (LLM-assisted extraction of a Knowledge Structure from free-form text; requires a configured LLM provider, see Operational Notes below).
- **Export:** `export_knowledge` (JSON-LD, Turtle, RDF/XML).
- **Ontology Validation:** `type_hierarchy` and `relation_type` extensions catch nonsense like "Earth orbits Pasta".
- **Content Ingestion:** `ingest_document` — fetch a URL and build a preliminary Knowledge Structure from metadata and keywords (optionally LLM-assisted, same provider requirement).
- **27 tools total** (see `docs/tools/index.md`).

### Reasoning & Conflict Resolution (ADR-001, ADR-002, ADR-008, ADR-009)
- **Belief Revision:** `record_inference` / `InferenceStep` objects, `resolve_inference_conflict` evolution operator, `rank_by_entrenchment` and `explain_inference` (surfaced via `explain_knowledge(object_id=...)`).
- **Conflict Detection:** `inference_confidence_conflict` and `stale_premise` extensions; `InferenceStalenessSweeper` proactively detects conflicts in the background.
- **Conflict Inbox:** `list_inference_conflicts` and `list_gossip_conflicts` drain (or peek) queues of reasoning and merge conflicts escalated by background sweeps/gossip, built for consumption by an unattended Critic agent.
- **Arbitration:** `arbitrate_inference_conflict` — interactive (caller supplies `winner_id`), unattended (`auto_resolve: true`), and batch (`conclusion_ids` + `winners`) modes, with optional `commit: true` to apply directly.

### Anti-Hallucination & Integrity
- **Provenance Enforcement:** `verify_source` creates cryptographically signed records; `validate_knowledge` unconditionally rejects forgeries.
- **Citation Verification:** `embedding_projection` extension mechanically detects references to non-existent sources.
- **Ontology Validation:** `type_hierarchy` and `relation_type` extensions enforce type-safe relations.
- **Atomic Evolution Validation:** `evolve_knowledge` runs a dry-run validation before committing, preventing any corrupted state from entering the history.
- **Field-Level Auto-Merge:** Conflicting edits to different fields of the same object are resolved automatically (ADR-007 Part 2).
- **Contradiction Detection:** `detect_contradictions` flags mutual exclusions and functional relation violations.

### Observability & Persistence
- **Persistent Storage:** SQLite by default; **PostgreSQL backend** available as a production-grade alternative (async storage ABC, pgvector support). Sessions, versions, and provenance secrets survive server restarts.
- **Event Bus Subscriptions:** Structured JSON logs of all lifecycle events (`SessionCreated`, `TransactionCommitted`, `GossipConflictDetected`, `InferenceConflictDetected`, etc.).
- **Runtime Metrics:** Invocation counts and execution times for every operation, accessible via `get_metrics`.

### RAG & Semantic Search
- **Embedding Pipeline:** A generalized Task Bus and Outbox Worker generate embeddings for new knowledge objects in the background.
- **Local, Token-Free Embeddings:** `fastembed` is the default embedding provider, with automatic fallback to HuggingFace.
- **Indexed & Vectorized Search:** `search_embeddings` in `cks-runtime` uses NumPy matrix operations for ~10× faster similarity search.

### Distributed Runtime Support
- **Gossip Replication:** Peer discovery, weighted peer selection (`PeerScheduler`), and background anti-entropy cycles (`GossipService`), backed by `cks-runtime` ADR-008.

### Security & Hardening
- **SSRF & DNS Rebinding Protection:** `verify_source` safely performs outbound HTTP checks.
- **Persistent Provenance Secrets:** The HMAC secret for signing verifications is stored alongside the database.
- **170+ tests** covering core functionality, security, and integrations.

## Operational Notes

- `construct_knowledge`, `ingest_document` (LLM mode), and `arbitrate_inference_conflict` (`auto_resolve: true`) require a configured LLM provider: either a reachable local Ollama server (`CKS_OLLAMA_HOST`, default `http://localhost:11434`, no API key) or `ANTHROPIC_API_KEY` with `CKS_LLM_PROVIDER=anthropic`. **This is unrelated to `search_semantic`**, which uses its own embedding stack (fastembed/HuggingFace) and works with no LLM provider configured. If an environment shows "no LLM provider available" errors, check Ollama reachability / `ANTHROPIC_API_KEY` first — this is an environment/config issue, not a code regression.

---

# Next Up — Autonomous Agents

**Goal:** Move from a tool for LLMs to a platform run by LLMs. The Critic
Agent was the first unattended agent built on the persistent outbox; the
same claim → resolve → complete/fail/dead-letter pattern is now the
template for every agent below, not a one-off.

## Critic Agent (Conflict Resolution Agent)

All of the supporting plumbing already exists and has shipped:
- Detection: `InferenceStalenessSweeper` (background), `GossipConflictDetected` / `InferenceConflictDetected` events.
- Queueing: `ConflictInbox`, drained via `list_gossip_conflicts` / `list_inference_conflicts`.
- Resolution primitives: `arbitrate_inference_conflict` (interactive, `auto_resolve`, and batch modes), `merge_branch` for structured diffs.

This closes the "Critic loop" gap identified in `cks-runtime`'s ADR-009.

- [x] **Critic Agent runtime loop:** `cks_mcp.critic_agent` (v1.30.0) — a standalone process with its own `Runtime` sharing storage with the main server, looping `claim_conflict_task` → `merge_branch` (gossip) / `arbitrate_inference_conflict` (inference) → `complete_conflict_task`. New `cks-critic-agent` console script.
- [x] **Dead-letter queue (DLQ):** conflicts the agent cannot confidently auto-resolve (a structural merge conflict, an unarbitrable `CKS-EXT-STALE-PREMISE` finding, or repeated failures past `CKS_CRITIC_MAX_RETRIES`) are dead-lettered via `dead_letter_conflict_task`, surfaced for human review via `list_dead_lettered_conflicts`.
- [x] **Task Bus integration:** built directly on the persistent outbox (`claim_conflict_task`/`fail_conflict_task`, `cks-runtime` 1.34.0+) the same Task Bus / Outbox Worker infrastructure already used for embeddings.
- [x] **Bugfix — mixed-diagnostic `inference_conflict` tasks:** `resolve_inference_conflict` used to send `conclusion_ids` and `stale_premise_ids` in one `arbitrate_inference_conflict` call whenever a task's payload carried both diagnostic codes; the tool rejects that combination (`invalid_parameter`), so every such task deterministically failed to `CKS_CRITIC_MAX_RETRIES` and was dead-lettered instead of resolved. Also fixed: a payload with *only* `CKS-EXT-STALE-PREMISE` findings was silently marked complete without ever calling the (already-existing) mechanical `stale_premise_ids` repair path. Now resolved via two independent calls, combined into one `Resolution`. Regression tests added in `tests/test_critic_agent.py`.
- [x] **LLM-assisted gossip conflict resolution:** `resolve_gossip_conflict` tool — mirrors `arbitrate_inference_conflict`'s three-path shape for structural merge conflicts, closing the asymmetry where inference conflicts had LLM arbitration but gossip conflicts required hand-rolled `resolutions`. Once shipped, the Critic Agent can auto-resolve structural gossip conflicts instead of dead-lettering them.
- [x] **Provenance conflict resolution:** `refresh_verification` tool (v1.34.0) + `critic_agent.py` support for `provenance_conflict` tasks.
- [x] **Temporal conflict resolution:** `resolve_temporal_conflict` tool (v1.35.0) + `critic_agent.py` support for `temporal_conflict` tasks.

### Hardening backlog (found during audit)
- [x] **Lease heartbeat for long-running resolutions:** `RuntimeStorage.touch_outbox_task(task_id)` (new — sync ABC in `cks-runtime`'s `storage.py`, async ABC in `async_storage.py`, implemented in `SQLiteStorage`/`PostgresStorage`, delegated by `SyncStorageAdapter`) renews an `IN_PROGRESS` task's `claimed_at`. `critic_agent._run_resolver_with_heartbeat` calls it every `CKS_CRITIC_HEARTBEAT_INTERVAL` seconds (default 60s, well under the 5-minute lease) while a resolver is running, and cancels the heartbeat once it finishes. If a renewal ever comes back `False` (lease already reclaimed by another worker), `_process_one` abandons the task without calling complete/fail/dead_letter, logs it, and counts it in `lease_lost` metrics — it does *not* try to fence/cancel the other worker.
  - **Not fully closed:** `touch_outbox_task` takes a task_id, not a fencing token, so it can't tell "I still legitimately hold this lease" apart from "someone else reclaimed it and is now also IN_PROGRESS" — see `test_touch_outbox_task_returns_false_once_reclaimed_by_another_worker`'s docstring in `cks-runtime`. In practice this closes the race for the common case (a live worker renewing well inside the lease window essentially never gets reclaimed), but a true fencing-token scheme is a further increment if double-processing is ever observed in practice.
- [x] **Circuit breaker on the LLM provider:** `critic_agent.LLMCircuitBreaker` — opens after `CKS_CRITIC_LLM_BREAKER_THRESHOLD` (default 3) consecutive LLM-attributable arbitration failures (`internal_error`/`llm_output_parse_error`/`invalid_arbiter_decision`/`missing_decision` — structural errors like `session_not_found` don't count), and while open, `_resolve_confidence_conflicts` skips the `arbitrate_inference_conflict(auto_resolve=True, ...)` call entirely for `CKS_CRITIC_LLM_BREAKER_COOLDOWN` seconds (default 60s) rather than burning an LLM call per queued task. Half-open after cooldown (next call is a trial, not an automatic re-open). The mechanical `stale_premise_ids` path never calls an LLM and keeps running regardless of breaker state.
- [x] **Critic-specific metrics:** `critic_agent.get_critic_metrics()` — processed/completed/retried/dead_lettered per task_type, `lease_lost`, and LLM breaker state, wired into the existing `get_metrics` tool as `critic_agent_metrics`.
  - **Not fully closed:** these counters are in-process. Since the Critic Agent runs as its *own* OS process by design, calling `get_metrics` against the main `cks-mcp` server reports all-zero Critic Agent counters even while a worker is actively processing tasks elsewhere against the same storage — see the caveat in `get_metrics`'s own docstring/schema. Real cross-process observability needs these persisted to shared storage (a metrics table, or piggybacking on the outbox tasks table's own aggregates) instead of kept in memory. Left as a follow-up, not attempted here.
- [ ] **Idempotency guard on resolution primitives:** still open. The heartbeat above closes most of the practical risk (a live worker essentially never loses its lease), but `merge_branch`/`arbitrate_inference_conflict` are still not guaranteed idempotent against a genuine double-claim (a crash right after a stale reclaim, not just a slow call). Revisit if `lease_lost`/dead-letter patterns in practice suggest it's actually happening.

---

## Enrichment Agent (external RAG / graph auto-growth)
**Goal:** the graph should be able to grow itself. `search_semantic` only
searches *inside* the existing graph — there is currently no way for CKS
to notice a gap (a low-confidence conclusion, a sparsely-connected
object, an explicit request) and go fill it from an external source on
its own. Same architectural pattern as the Critic Agent: a new outbox
task_type (`enrichment_request`), a `claim_enrichment_task`, and a
resolver loop — not a new concurrency model.

Design (see project discussion for full rationale):
- [ ] **`enrichment_request` task type + `claim_enrichment_task` tool**, mirroring `claim_conflict_task`.
- [ ] **Manual trigger:** new `request_enrichment(session_id, object_id, hint?)` tool — the interactive counterpart, like `list_gossip_conflicts` vs. `claim_conflict_task`.
- [ ] **Proactive trigger:** a sweeper (same shape as `InferenceStalenessSweeper`) that finds under-sourced objects — low confidence, zero `verify_source` provenance, sparse neighborhood — and enqueues `enrichment_request` tasks on its own.
- [ ] **Query builder:** derive a search query from an object's `identity.name` + surrounding relations (LLM-assisted, reusing `cks_mcp.llm_providers` dispatch already used by `construct_knowledge`/`arbitrate_inference_conflict`).
- [ ] **External source adapters:** start with one (Wikipedia — simplest free API), then arXiv, then PubMed. Each adapter returns a list of candidate URLs, not content — content extraction stays `ingest_document`'s job.
- [ ] **robots.txt compliance:** cks-mcp currently has *no* robots.txt check anywhere (`ingest_document`/`verify_source` only do SSRF/DNS-rebinding protection). Needed before any agent fetches URLs unattended, at scale, without a human approving each one.
- [ ] **Candidate filtering/ranking before spending an `ingest_document` call:** domain allow/deny lists, relevance scoring, dedup against already-ingested sources. (Adapted from patterns in an unrelated internal crawler project's `rank_and_deduplicate_targets`/`score_targets`/`is_low_value_target_url` — reimplemented against CKS's own data model, not a code port: that project's CRDT swarm coordination doesn't apply here.)
- [ ] **Confidence-gated commit:** don't write every fetched result into the graph. Gate on relevance/source-quality thresholds before calling `evolve_knowledge`, and if nothing clears the bar, resolve the task as "nothing relevant found" rather than a failure — the same silent-vs-honest distinction just fixed in the Critic Agent's stale-premise handling applies here too.
- [ ] **Provenance + linking:** `verify_source` for the fetched URL, then `evolve_knowledge(add_relation, relation_type="enriched_by")` linking the new object(s) to the one that triggered the search.
- [ ] **`cks-enrichment-agent` console script**, same shape as `cks-critic-agent`.

## Future Agents (backlog, not yet designed in detail)
Same outbox-task pattern, lower priority than the Enrichment Agent above:
- **Contradiction Agent:** `detect_contradictions` exists as an on-demand extension but nothing runs it proactively in the background the way `InferenceStalenessSweeper` does for inference conflicts. A sweeper + `contradiction_conflict` task type would close that gap.
- **Source Verification Agent:** periodically re-runs `verify_source` against already-committed claims to catch sources that have gone stale, moved, or disappeared since they were first cited.
- **Compaction/Pruning Agent:** uses `compare_versions`/`list_versions` to find sessions with runaway version history or abandoned branches and proposes archival — human-approved by default, not auto-destructive.

---

# Roadmap to v2.0

## Production & Scale
**Goal:** Harden the server for reliable, persistent, and scalable deployments.

- [x] **PostgreSQL Backend:** A production-grade storage backend as an alternative to SQLite. *(shipped — see cks-runtime >=1.21.0)*
- [x] **Local Embedding Models:** `fastembed` integrated as the default, fully offline, free semantic search provider.
- [ ] **Performance & Stress Testing:** Benchmark the full `cks-core` -> `cks-runtime` -> `cks-mcp` pipeline.

> Docker distribution was previously listed here and has been intentionally descoped: the project runs fine without a container image, and it was a recurring source of confusion about what's actually required to run the server. Not planned.

## Ecosystem & Distribution
**Goal:** Make CKS the default knowledge layer for LLM applications.

- [x] **Official Documentation Site:** `docs/index.md`, `docs/getting-started.md`, the full `docs/tools/` reference (all 27 tools), `docs/security.md`, `docs/extensions.md`, `docs/protocol/` (Resources & Prompts), `docs/architecture/` (with a dedicated request lifecycle page), and `docs/adr/` are all in place. Remaining: publish this as an actual hosted site (the mkdocs hub currently lives in `cks-core` and needs its nav updated to include these pages).
- [ ] **Dedicated MCP Client:** A lightweight desktop or web client specifically designed for managing CKS graphs.
- [ ] **Domain-Specific Constraint Packs:** Pre-built validation rules for scientific, legal, and medical knowledge.

---

# Beyond 2.0 — The Knowledge Platform

Once the core platform is stable and autonomous, we will focus on transforming it from a single server into a collaborative ecosystem:

- **Distributed Knowledge Graphs:** Multiple `cks-mcp` instances sharing and synchronizing a common, versioned knowledge base via `cks-runtime` — gossip replication groundwork already shipped (ADR-008); this item extends it into a fully synchronized multi-instance deployment story.
- **Federated Learning on Graphs:** Privacy-preserving model training across distributed, versioned knowledge graphs.
- **MCP Resource Exposure:** Expose canonical knowledge structures as MCP Resources, allowing LLMs to browse and query a knowledge base directly.
