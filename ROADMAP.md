# Roadmap

This roadmap outlines the planned evolution of the CKS MCP Platform.
It reflects the current state of the project and charts the course
towards a stable, production-ready platform and beyond.

---

# Current Status (v1.41.x — August 2026)

CKS has matured into a **52‑tool, 1 700+ test autonomous knowledge platform**
with three persistent agents, five background sweepers, and a plugin framework.
It provides LLMs with a verifiable, self‑maintaining knowledge backbone that
runs entirely on local infrastructure (SQLite/Postgres, fastembed, optional
Ollama). See [README](README.md#available-tools) for the full tool list.

## ✅ Completed Milestones

### Core Server & Protocol
- Full MCP protocol compliance (`initialize`, `tools/list`, `tools/call`, `ping`).
- MCP Resources and Prompts for seamless UI integration.
- JSON-RPC over stdio with structured, LLM-friendly error responses.
- CI/CD: `ruff` linting and `mypy` type checking run on every push.
- **Plugin Framework:** `CksPlugin` abstract base class, `PluginRegistry`,
  and the first two plugins (`FastEmbedPlugin`, `GossipPlugin`).
  `list_plugins` tool shows every registered plugin.

### Canonical Tools (46 total – see `docs/tools/index.md`)
- **Knowledge Lifecycle:** `validate_knowledge`, `evolve_knowledge`,
  `serialize_knowledge`, `explain_knowledge`.
- **Version Control:** `list_versions`, `compare_versions`, `revert_version`.
- **Branching & Merging:** `create_branch`, `merge_branch`, `merge_knowledge`,
  `close_session`, `fork_sandbox`.
- **Graph Exploration:** `query_subgraph` (compact mode + budget),
  `search_semantic` (real embeddings via fastembed/HuggingFace, `min_score`
  threshold, similarity scores), `visualize_graph` (Mermaid export,
  structure + inference modes).
- **Verification & Integrity:** `verify_source` (cryptographic signing),
  `detect_contradictions` (MutualExclusionRule / FunctionalRelationRule).
- **AI-Assisted & Ingestion:** `construct_knowledge`, `suggest_evolution`,
  `ingest_document` (optionally LLM-assisted), `request_enrichment`.
- **Export & Observability:** `export_knowledge` (JSON-LD, Turtle, RDF/XML),
  `export_session`, `get_metrics`, `export_storage`, `import_storage`,
  `migrate_storage` (ADR-012).
- **Memory & Persistence:** `register_graph`, `get_graph`, `list_graphs`,
  `search_graphs`, `check_graph_freshness` — Memory Agent v1 + gallery.
- **Conflict Resolution:** `list_gossip_conflicts`, `list_inference_conflicts`,
  `arbitrate_inference_conflict`, `resolve_gossip_conflict`,
  `refresh_verification`, `resolve_temporal_conflict`,
  `claim_conflict_task`, `complete_conflict_task`, `fail_conflict_task`,
  `dead_letter_conflict_task`, `list_dead_lettered_conflicts`.
- **Reasoning & Explainability:** `explain_diff`, `explain_knowledge(object_id=…)`
  for inference chains; `inference_confidence_conflict` and `stale_premise`
  extensions.
- **Ontology Validation:** `type_hierarchy` and `relation_type` extensions.

### Autonomous Agents & Background Workers
- **Critic Agent** (`cks‑critic‑agent`): resolves `gossip_conflict`,
  `inference_conflict`, `provenance_conflict`, `temporal_conflict`, and
  `contradiction_detected` tasks from the outbox. Features LLM circuit breaker,
  lease heartbeat, and dead‑letter queue.
- **Enrichment Agent** (`cks‑enrichment‑agent`): searches external sources
  (Wikipedia, arXiv) for missing context, filters by relevance/authority,
  respects `robots.txt`, and links findings back with provenance.
- **Memory Agent v1:** three MCP tools + `graph_registry` table let LLMs
  save, find, and reuse knowledge graphs across conversations.
- **Five background sweepers** continuously patrol the knowledge base:
  - `InferenceStalenessSweeper` – detects stale reasoning chains.
  - `ProvenanceStalenessSweeper` – detects expired verification records.
  - `TemporalStalenessSweeper` – detects facts with expired `valid_until`.
  - `GraphFreshnessSweeper` – detects outdated registered graphs.
  - `ContradictionSweeper` – detects logical contradictions.
- **Persistent Outbox + DLQ:** all sweepers escalate tasks into a unified
  outbox; dead‑letter queue for unresolvable conflicts.

### Storage & Backup
- **Three storage backends:** InMemory, SQLite, PostgreSQL (async, pgvector).
- **Backup & Migration (ADR-012):** `export_storage`, `import_storage`,
  `migrate_storage` tools allow full backup, restore, and migration between
  backends.

### Security, Observability & Testing
- **SSRF & DNS Rebinding Protection** on all outbound HTTP calls.
- **Persistent Provenance Secrets** survive server restarts.
- **Telemetry:** per‑tool call counts, success rates, latency percentiles.
- **1 650+ tests** across three repositories (cks‑core, cks‑runtime, cks‑mcp).

---

# Next Up — Memory Agent v2, Gallery & Beyond

**Goal:** Make CKS the default knowledge layer for LLM applications,
with a public gallery of reusable graphs and cross‑graph analysis.

## Memory Agent v2 — Autonomous Graph Updates (🔴 P0)

- [x] **Memory Agent v2:** `check_component_versions` (v1.42.0), `update_registered_graph` (v1.43.0), `GraphAutoUpdateSweeper` (cks‑runtime v1.42.0) — graphs can now detect outdated components, update them automatically, and run the check on a schedule.
- [x] **`explain_graph` tool** (v1.44.0) — generates a human-readable Markdown report for any registered graph.
- [x] **Human-in-the-loop:** `review_dead_letter`, `approve_resolution`, `reject_resolution` tools (v1.45.0) — manual dead-letter recovery with a simple review/approve/reject workflow.

## Graph Gallery (🟡 P1)

- [ ] **Public gallery UI:** a web page (or dedicated MCP resource) that
  lists every graph registered with `public: true`.
- [ ] **Filters:** by category, tags, date, popularity.
- [ ] **Clone a public graph:** allow users to import a public graph into
  their own session as a starting point.
- [ ] **Ratings / stars** (optional, for community curation).

## Plugin Ecosystem Documentation (🟢 P2)

- [ ] **"Creating your first plugin" tutorial** in `docs/plugins.md`.
- [ ] **Template repository:** `cks‑plugin‑template` with a minimal example
  plugin and CI pipeline.
- [ ] **Plugin discovery:** show installed plugins in the gallery and let
  users browse a community plugin registry (future).

## Cross‑Graph Analysis (🔵 P3)

- [ ] **`compare_graphs(graph_a, graph_b)`** – find shared objects,
  contradictions, and potential links between two separate graphs.
- [ ] **`merge_graphs(graph_a, graph_b)`** – combine two graphs with
  conflict‑controlled merge.
- [ ] **`link_graphs(graph_a, graph_b, relation_type)`** – establish a
  relation between objects in different graphs.

---

# Beyond 2.0 — The Knowledge Platform

Once the core platform is stable and autonomous, we will focus on
transforming it from a single server into a collaborative ecosystem:

- **Distributed Knowledge Graphs:** multiple `cks‑mcp` instances sharing
  and synchronising a common, versioned knowledge base via `cks‑runtime`
  gossip replication (ADR‑008). Extend into a fully synchronised multi‑instance
  deployment.
- **Federated Learning on Graphs:** privacy‑preserving model training across
  distributed, versioned knowledge graphs.
- **MCP Resource Exposure:** expose canonical knowledge structures as MCP
  Resources, allowing LLMs to browse and query a knowledge base directly.
- **Domain‑Specific Constraint Packs:** pre‑built validation rules for
  scientific, legal, and medical knowledge.
- **Community Plugin Registry:** a public index where developers can publish
  and discover CKS plugins.

---

## Operational Notes

- `construct_knowledge`, `ingest_document` (LLM mode), and
  `arbitrate_inference_conflict` (`auto_resolve: true`) require a configured
  LLM provider: either a reachable local Ollama server (`CKS_OLLAMA_HOST`,
  default `http://localhost:11434`, no API key) or `ANTHROPIC_API_KEY` with
  `CKS_LLM_PROVIDER=anthropic`. **This is unrelated to `search_semantic`**,
  which uses its own embedding stack (fastembed/HuggingFace) and works with
  no LLM provider configured.