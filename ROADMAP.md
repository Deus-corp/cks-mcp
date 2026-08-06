# Roadmap

This roadmap outlines the planned evolution of the CKS MCP Platform.
It reflects the current state of the project and charts the course
towards a stable, production-ready platform and beyond.

---

# Current Status (v1.49.x — August 2026)

CKS has matured into a **53‑tool, 1 750+ test autonomous knowledge platform**
with four persistent agents, six background sweepers, a plugin framework, and
a CRDT adapter (ADR‑013). It provides LLMs with a verifiable, self‑maintaining
knowledge backbone that runs entirely on local infrastructure (SQLite/Postgres,
fastembed, optional Ollama). See [README](README.md#available-tools) for the
full tool list.

## ✅ Completed Milestones

### Core Server & Protocol
- Full MCP protocol compliance.
- MCP Resources, Prompts, JSON-RPC over stdio, CI/CD (ruff + mypy).
- **Plugin Framework** (`CksPlugin`, `PluginRegistry`, `list_plugins`).
- **CRDT Adapter** (ADR‑013): G‑Set + Merkle Tree (Stage 1), MV‑Register +
  fork detection + conflict events (Stage 2), ForkResolutionAgent (Stage 3).

### Canonical Tools (53 total)
- Knowledge Lifecycle, Version Control, Branching & Merging, Graph Exploration,
  Verification & Integrity, AI‑Assisted & Ingestion, Export & Observability,
  Memory & Persistence, Conflict Resolution, Reasoning & Explainability,
  Ontology Validation.

### Autonomous Agents & Background Workers
- **Critic Agent** (`cks‑critic‑agent`): 6 conflict types (gossip, inference,
  provenance, temporal, contradiction, crdt_fork).
- **Enrichment Agent** (`cks‑enrichment‑agent`): Wikipedia, arXiv.
- **Fork Resolution Agent** (`cks‑fork‑agent`): CRDT fork resolution with
  causality‑based winner selection.
- **Memory Agent v2:** `check_component_versions`, `update_registered_graph`,
  `GraphAutoUpdateSweeper`, `explain_graph`.
- **Six background sweepers:** Inference, Provenance, Temporal, GraphFreshness,
  Contradiction, GraphHealth.
- **Persistent Outbox + DLQ** for all agents and sweepers.

### Observability & Human‑in‑the‑loop
- **Cost & Token Tracking** (`LLMTelemetry` + `get_metrics`).
- **Graph Health Score** (`check_graph_health` + `GraphHealthSweeper`).
- **Human‑in‑the‑loop:** `review_dead_letter`, `approve_resolution`,
  `reject_resolution`.

### Storage & Backup
- **Three storage backends** (InMemory, SQLite, PostgreSQL).
- **Backup & Migration (ADR‑012)**.

### Security & Testing
- SSRF & DNS Rebinding Protection, Persistent Provenance Secrets.
- **1 750+ tests** across cks‑core, cks‑runtime, cks‑mcp.

---

# Next Up — LCA Arbiter, Visualization, Orchestrator

## LCA Arbiter (🔴 P0)

**Goal:** Replace the mechanical tie‑break in ForkResolutionAgent with a
topological arbiter that understands the DAG structure of conflicts.

- [ ] **`find_lca`** – find the Lowest Common Ancestor of two conflicting
  objects via backward BFS through `depends_on` relations.
- [ ] **`extract_delta`** – extract the subgraph between the LCA and each
  conflicting branch.
- [ ] **`classify_conflict`** – classify conflicts as non‑overlapping,
  competing claims, or erroneous branch.
- [ ] **`resolve_with_lca`** – create a `Resolution` object with
  `strategy_applied`, `resolved_branches`, `common_ancestor`, `rationale`,
  and `depends_on` both branches.
- [ ] **Integration with ForkResolutionAgent** – optional `use_lca` flag;
  fallback to mechanical resolution when LCA is unavailable.

## Visualization & Dashboard (🟡 P1)

**Goal:** An interactive web dashboard for exploring the knowledge graph,
inference chains, and fork resolution.

- [ ] **React Flow dashboard** with custom nodes (Definition, Claim, Fork,
  Resolution).
- [ ] **Fork & Conflict Diff View** – highlight parallel branches from LCA.
- [ ] **Inference Chain Inspector** – trace `depends_on` from conclusion to
  base axioms.
- [ ] **Real‑time Gossip Visualizer** – live updates via WebSocket/SSE.
- [ ] **Color‑coded nodes** by type and status (stale, conflict, resolved).

## Multi‑Agent Orchestrator (🟢 P2)

**Goal:** A hierarchical orchestration layer (Overseer → Meta‑Agent → Node)
for coordinating multiple CKS agents in a pipeline.

- [ ] **Researcher → Critic → Synthesizer → Arbiter** pipeline.
- [ ] **`CKSAgentOrchestrator`** class with pluggable roles and LLM backends.
- [ ] **CRDT‑based communication** between orchestration layers.
- [ ] **Integration with existing agents** (Critic, Enrichment, Fork).

---

## Graph Gallery (🟡 P1)

- [ ] **Public gallery UI** – browse graphs registered with `public: true`.
- [ ] **Filters** by category, tags, date, popularity.
- [ ] **Clone a public graph** into the user's own session.

## Plugin Ecosystem Documentation (🟢 P2)

- [ ] **"Creating your first plugin" tutorial** in `docs/plugins.md`.
- [ ] **Template repository** `cks‑plugin‑template` with CI.
- [ ] **Plugin discovery** in the gallery.

## Cross‑Graph Analysis (🔵 P3)

- [ ] **`compare_graphs(graph_a, graph_b)`** – find shared objects and
  contradictions.
- [ ] **`merge_graphs(graph_a, graph_b)`** – combine two graphs with
  conflict‑controlled merge.
- [ ] **`link_graphs(graph_a, graph_b, relation_type)`** – establish
  cross‑graph relations.

---

# Beyond 2.0 — The Knowledge Platform

- **Distributed Knowledge Graphs** – multi‑instance gossip sync.
- **Federated Learning on Graphs** – privacy‑preserving training.
- **MCP Resource Exposure** – browsable knowledge bases.
- **Domain‑Specific Constraint Packs** – science, law, medicine.
- **Community Plugin Registry** – public index of CKS plugins.

---

## Operational Notes

- `construct_knowledge`, `ingest_document` (LLM mode), and
  `arbitrate_inference_conflict` (`auto_resolve: true`) require a configured
  LLM provider: either a reachable local Ollama server (`CKS_OLLAMA_HOST`,
  default `http://localhost:11434`, no API key) or `ANTHROPIC_API_KEY` with
  `CKS_LLM_PROVIDER=anthropic`. **This is unrelated to `search_semantic`**,
  which uses its own embedding stack (fastembed/HuggingFace) and works with
  no LLM provider configured.