# Roadmap

This roadmap outlines the planned evolution of the CKS MCP Platform.
It reflects the current state of the project and charts the course
towards a stable, production-ready platform and beyond.

---

# Current Status (v1.59.0 — August 2026)

CKS MCP has matured into a **64-tool, 1 750+ test autonomous knowledge platform** with:

- Five persistent agents (Critic, Enrichment, Fork Resolution, Pipeline, and in-process sweepers).
- Seven background sweepers.
- Plugin framework.
- LLM abstraction layer (Ollama, Anthropic, OpenAI-compatible).
- CRDT adapter (ADR-013 Stage 1–3).
- Phase 1 safety infrastructure.
- Start Pipeline MCP tool (`start_pipeline`) for graph-driven pipeline runs.

## ✅ Completed Milestones

### Core Server & Protocol
- Full MCP protocol compliance.
- MCP Resources, Prompts, JSON-RPC over stdio, CI/CD (ruff + mypy).
- **Optional HTTP transport** (`CKS_MCP_HTTP_PORT`) with CORS, for direct
  integration with web frontends like `cks-studio`.
- **Plugin Framework** (`CksPlugin`, `PluginRegistry`, `list_plugins`), fully
  async lifecycle (`setup`/`teardown`).
- **CRDT Adapter** (ADR‑013): G‑Set + Merkle Tree (Stage 1), MV‑Register +
  fork detection + conflict events (Stage 2), ForkResolutionAgent (Stage 3).

### Canonical Tools (63 total)
- Knowledge Lifecycle, Version Control, Branching & Merging, Graph Exploration,
  Verification & Integrity, LLM & AI, Export & Observability,
  Memory & Persistence, Gossip & Conflict Resolution, Agent Observability,
  Agent Control.

### LLM Integration
- **Shared `LLMClient`** (`cks_mcp.llm.client`) unifying Ollama, Anthropic,
  and any OpenAI‑compatible endpoint (OpenAI, Groq, DeepSeek, Together,
  LM Studio, vLLM) behind one tool‑calling and single‑shot interface.
- **`ai_chat` tool** — bounded agentic loop (max 8 iterations) that can call
  any safe MCP tool, with session pinning and a denylist for
  server‑management tools.
- **`get_llm_status` / `list_llm_models`** — read‑only provider/model
  introspection for thin clients (e.g. `cks-studio` Settings page).

### Multi‑Agent Pipeline (ADR‑007)
- **`CKSAgentOrchestrator`** (`run_sequential` / `run_concurrent`) coordinating
  agent steps through the persistent outbox and CRDT registers.
- **Researcher → Synthesizer → Reviewer → Arbiter** pipeline, each step an
  `AgentStep` committing via `evolve_knowledge` with full provenance.
- **`cks-pipeline-agent`** console script running the pipeline autonomously.
- **Phase 1 safety infrastructure** — `fork_sandbox` isolation, token/cost
  budgeting (`TokenBudget`), idempotency cache, graceful degradation.

### LCA Arbiter
- **Topology‑aware fork resolution** (`lca_arbiter.py`) — finds the lowest
  common ancestor of conflicting objects via `query_subgraph`, classifies
  conflicts (`non_overlapping`, `competing_claims`, `erroneous_branch`), and
  auto‑merges disjoint branches or escalates a `Resolution` object for review.
- **Integrated into `ForkResolutionAgent`** via `use_lca` (default `true`),
  with fallback to the mechanical tie‑break when LCA is unavailable.

### Autonomous Agents & Background Workers
- **Critic Agent** (`cks‑critic‑agent`): 6 conflict types (gossip, inference,
  provenance, temporal, contradiction, crdt_fork).
- **Enrichment Agent** (`cks‑enrichment‑agent`): Wikipedia, arXiv.
- **Fork Resolution Agent** (`cks‑fork‑agent`): CRDT fork resolution, now
  LCA‑aware (see above).
- **Pipeline Agent** (`cks-pipeline-agent`): Researcher/Synthesizer/Reviewer/
  Arbiter orchestration.
- **Memory Agent v2:** `check_component_versions` (Python and JS/TS via
  `package.json`), `update_registered_graph`, `GraphAutoUpdateSweeper`,
  `explain_graph`.
- **Seven background sweepers:** Inference, Provenance, Temporal,
  GraphFreshness, Contradiction, GraphHealth, GraphAutoUpdate.
- **Persistent Outbox + DLQ** for all agents and sweepers.

### Agent Observability & Control (ADR‑015, ADR‑016)
- **`list_agents` / `agent_status`** — status of in‑process sweepers.
- **`list_processes` / `process_status`** — liveness of standalone agent
  processes (Critic, Enrichment, Fork Resolution, Pipeline).
- **`start_agent` / `stop_agent`** — runtime‑persisted sweeper enable/disable
  (`cks_sweeper_control` table, ADR‑015).
- **`request_process_stop`** — graceful remote shutdown of a standalone agent
  process via its liveness row (ADR‑016).

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
- **1 750+ tests** across cks‑core, cks‑runtime, cks‑mcp (873 passed, 6 skipped
  in cks‑mcp alone — skips require Postgres/optional providers).

---

# Next Up

## Real MCP Session Presence (🟢 in progress)

- SSE endpoint (`GET /events`, `GET /events/{session_id}`) publishing `SessionCreated`, `VersionCreated`, `TransactionCommitted`, `GossipConflictDetected`, `CRDTForkDetected`, etc., so thin clients (cks-studio) can subscribe and update live. Implemented in `src/cks_mcp/transport/sse.py` + `src/cks_mcp/transport/http_events.py`, wired into the optional HTTP transport (`CKS_MCP_HTTP_PORT`); cks-studio now consumes it via `useSessionEvents`. WebSocket was considered and dropped in favor of SSE (one-way is sufficient, simpler to consume from the browser). Remaining: `CKS_MCP_HTTP_TOKEN` auth on the endpoint (extension point left in `transport/http_events.py`, not yet implemented).

## Graph Gallery: Clone & Filters (🟡 P1)

- `clone_graph` MCP tool to copy a public graph into the caller's session.
- Graph gallery filters and health score integration.

## Cross-Graph Analysis (🔵 P3)

- `compare_graphs(graph_a, graph_b)` — shared objects and contradictions.
- `merge_graphs(graph_a, graph_b)` — conflict-controlled merge.
- `link_graphs(graph_a, graph_b, relation_type)` — cross-graph relations.

## Plugin Ecosystem Documentation (🟢 P2)

- «Creating your first plugin» tutorial.
- Template repository `cks-plugin-template`.
- Plugin discovery in gallery.

## Visualization & Dashboard (🟡 P1)

- Real-time Gossip Visualizer.
- Color-coded nodes by status (stale, conflict, resolved).

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