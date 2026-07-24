# Roadmap

This roadmap outlines the planned evolution of the CKS MCP Server.
It reflects the current state of the project and charts the course
towards a stable, production-ready platform and beyond.

---

# Current Status (v1.6.x)

The project has matured into a robust platform. It provides LLMs with
a verifiable, persistent knowledge backbone, semantic search, and a full
suite of tools for knowledge lifecycle management.

## ✅ Completed Milestones

### Core Server & Protocol
- Full MCP protocol compliance (`initialize`, `tools/list`, `tools/call`, `ping`).
- MCP Resources and Prompts for seamless UI integration.
- JSON-RPC over stdio with structured, LLM-friendly error responses.

### Canonical Tools (15 total)
- **Knowledge Lifecycle:** `validate_knowledge`, `evolve_knowledge`, `serialize_knowledge`, `explain_knowledge`.
- **Version Control:** `list_versions`, `compare_versions`, `revert_version`.
- **Branching & Merging:** `create_branch`, `merge_branch`, `merge_knowledge`, `close_session`.
- **Graph Exploration:** `query_subgraph` (with compact mode and budget), `search_semantic` (real embeddings via HuggingFace).
- **Audit & Metrics:** `get_metrics` for runtime statistics.

### Anti-Hallucination & Integrity
- **Provenance Enforcement:** `verify_source` creates cryptographically signed records; `validate_knowledge` unconditionally rejects forgeries.
- **Citation Verification:** `embedding_projection` extension mechanically detects references to non-existent sources.
- **Atomic Evolution Validation:** `evolve_knowledge` runs a dry-run validation before committing, preventing any corrupted state from entering the history.

### Observability & Persistence
- **Persistent SQLite Storage:** Sessions, versions, and provenance secrets survive server restarts.
- **Event Bus Subscriptions:** Structured JSON logs of all lifecycle events (`SessionCreated`, `TransactionCommitted`, etc.).
- **Runtime Metrics:** Invocation counts and execution times for every operation, accessible via `get_metrics`.

### RAG & Semantic Search
- **Embedding Pipeline:** A generalized Task Bus and Outbox Worker generate embeddings for new knowledge objects in the background.
- **True Semantic Search:** `search_semantic` uses real HuggingFace embeddings to find concepts by meaning, not keywords.

### Security & Hardening
- **SSRF & DNS Rebinding Protection:** `verify_source` safely performs outbound HTTP checks.
- **Persistent Provenance Secrets:** The HMAC secret for signing verifications is stored alongside the database.
- **50+ tests** covering core functionality, security, and integrations.

---

# Roadmap to v2.0

## AI-Powered Knowledge Management
**Goal:** Move from a tool for LLMs to a platform run by LLMs.

- [ ] **Conflict Resolution Agent:** An autonomous agent that resolves merge conflicts using structured diffs, ReAct loops, and a DLQ via the Task Bus.
- [ ] **`construct_knowledge` Tool:** Use an LLM to parse natural language directly into a `KnowledgeStructure`.
- [ ] **Self-Healing Graphs:** Agents that automatically repair constraint violations or suggest improvements to the knowledge graph.

## Production & Scale
**Goal:** Harden the server for reliable, persistent, and scalable deployments.

- [ ] **Docker Distribution:** Publish an official Docker image for easy deployment.
- [ ] **PostgreSQL Backend:** A production-grade storage backend as an alternative to SQLite.
- [ ] **Local Embedding Models:** Integrate `fastembed` or `llama-cpp-python` for fully offline, free semantic search.
- [ ] **Performance & Stress Testing:** Benchmark the full `cks-core` -> `cks-runtime` -> `cks-mcp` pipeline.

## Ecosystem & Distribution
**Goal:** Make CKS the default knowledge layer for LLM applications.

- [ ] **Official Documentation Site:** Comprehensive guides, API references, and tutorials.
- [ ] **Dedicated MCP Client:** A lightweight desktop or web client specifically designed for managing CKS graphs.
- [ ] **Domain-Specific Constraint Packs:** Pre-built validation rules for scientific, legal, and medical knowledge.

---

# Beyond 2.0 — The Knowledge Platform

Once the core platform is stable and autonomous, we will focus on transforming it from a single server into a collaborative ecosystem:

- **Distributed Knowledge Graphs:** Multiple `cks-mcp` instances sharing and synchronizing a common, versioned knowledge base via `cks-runtime`.
- **Federated Learning on Graphs:** Privacy-preserving model training across distributed, versioned knowledge graphs.
- **MCP Resource Exposure:** Expose canonical knowledge structures as MCP Resources, allowing LLMs to browse and query a knowledge base directly.