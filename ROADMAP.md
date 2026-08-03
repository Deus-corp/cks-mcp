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

# Next Up

## Critic Agent (Conflict Resolution Agent)
**Goal:** Move from a tool for LLMs to a platform run by LLMs — this is the literal next step for the project.

All of the supporting plumbing already exists and has shipped:
- Detection: `InferenceStalenessSweeper` (background), `GossipConflictDetected` / `InferenceConflictDetected` events.
- Queueing: `ConflictInbox`, drained via `list_gossip_conflicts` / `list_inference_conflicts`.
- Resolution primitives: `arbitrate_inference_conflict` (interactive, `auto_resolve`, and batch modes), `merge_branch` for structured diffs.

This closes the "Critic loop" gap identified in `cks-runtime`'s ADR-009.

- [x] **Critic Agent runtime loop:** `cks_mcp.critic_agent` (v1.30.0) — a standalone process with its own `Runtime` sharing storage with the main server, looping `claim_conflict_task` → `merge_branch` (gossip) / `arbitrate_inference_conflict` (inference) → `complete_conflict_task`. New `cks-critic-agent` console script.
- [x] **Dead-letter queue (DLQ):** conflicts the agent cannot confidently auto-resolve (a structural merge conflict, an unarbitrable `CKS-EXT-STALE-PREMISE` finding, or repeated failures past `CKS_CRITIC_MAX_RETRIES`) are dead-lettered via `dead_letter_conflict_task`, surfaced for human review via `list_dead_lettered_conflicts`.
- [x] **Task Bus integration:** built directly on the persistent outbox (`claim_conflict_task`/`fail_conflict_task`, `cks-runtime` 1.34.0+) the same Task Bus / Outbox Worker infrastructure already used for embeddings.

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
