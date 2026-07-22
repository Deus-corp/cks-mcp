# Roadmap

This roadmap outlines the planned evolution of the CKS MCP Server.
It reflects the current state of the project and charts the course
towards a stable, production-ready v1.0.0 release and beyond.

---

# Current Status (v1.2.0)

The project has matured significantly beyond the initial prototype.
The core infrastructure for providing LLMs with verifiable knowledge
is in place and has been battle-tested through multiple experiments.

## ✅ Completed Milestones

### Core MCP Server

- Full MCP protocol compliance (`initialize`, `tools/list`, `tools/call`, `ping`).
- JSON-RPC over stdio transport.
- Structured error responses for LLM-friendly diagnostics.

### Canonical Tools

- `validate_knowledge` with support for opt-in, per-call extensions.
- `serialize_knowledge` to produce canonical JSON.
- `explain_knowledge` for structural summaries.
- `evolve_knowledge` to apply Genesis/Decay operators.
- `query_subgraph` — extract a k-hop neighbourhood with filters and budget.

### Anti-Hallucination Features

- **Citation Verification:** The `embedding_projection` extension mechanically detects references to non-existent sources.
- **Verification Integrity:** The `verify_source` tool performs real HTTP checks and creates cryptographically signed `VerificationRecord` objects.
- **Provenance Enforcement:** `validate_knowledge` unconditionally verifies the signature of every `VerificationRecord`, making it impossible for an LLM to fabricate a source check.
- **Subgraph Exploration:** LLMs can now traverse knowledge graphs systematically without hallucinations, with explicit truncation signals.

### Security & Robustness

- **SSRF Protection:** Built-in URL validation blocks requests to private, loopback, and cloud metadata IPs.
- **DNS Rebinding Prevention:** HTTP connections are pinned to the IP address resolved during the safety check, neutralizing a class of SSRF attacks.
- **Auditability:** Every operation creates immutable versions, providing a full history of all AI-generated knowledge.
- **Test Suite:** 26+ tests covering core functionality, extensions, and security.
- **Test Suite:** 41+ tests covering core functionality, extensions, and security.

---

# Roadmap to v1.0.0 +

## Version 0.7 — Observability & Developer Experience

**Goal:** Make the system more transparent and easier to develop against.

- [ ] **Execution Event Stream:** Expose `cks-runtime`'s new Event System through the MCP server, allowing clients to subscribe to `SessionCreated`, `TransactionCommitted`, `ValidationFailed` and other events.
- [ ] **Structured Activity Logs:** Generate machine-readable logs for every tool call and internal operation.
- [ ] **Improved Error Taxonomy:** Expand structured error codes to cover all known failure modes (network errors, timeouts, schema mismatches).

## Version 0.8 — Advanced Tools & LLM Integration

**Goal:** Expand the range of canonical operations available to LLMs.

- [ ] **Construct Knowledge from Text:** A new `construct_knowledge` tool that uses an LLM to parse natural language into a `KnowledgeStructure`.
- [ ] **Batch Operations:** Tools for validating, comparing, and merging multiple structures at once.
- [ ] **LLM Client Improvements:** Enhance `llm_client/` with support for more providers and a library-friendly API.

## Version 0.9 — Production Readiness

**Goal:** Harden the server for reliable, persistent deployments.

- [ ] **Persistent Sessions & Secrets:** Move session storage and the provenance signing secret to durable storage (e.g., SQLite), making data survive server restarts.
- [ ] **Docker Distribution:** Publish an official Docker image for easy deployment.
- [ ] **Performance & Stress Testing:** Benchmark the full `cks-core` -> `cks-runtime` -> `cks-mcp` pipeline and identify bottlenecks.

## Version 1.0 — Stable Release

**Goal:** A stable, documented platform for verifiable AI knowledge.

- [ ] **Frozen Public API:** All tool schemas, configuration formats, and core behaviors are declared stable.
- [ ] **Complete Documentation:** Exhaustive API docs, a "Getting Started" guide, and best-practice tutorials for using the server with different LLMs.
- [ ] **Production-Grade Test Coverage:** >90% test coverage including end-to-end integration tests.

---

# Beyond 1.0 — The Knowledge Platform

Once the core platform is stable, we will focus on transforming it from a single server into a collaborative ecosystem:

- **Distributed Knowledge Graphs:** Multiple `cks-mcp` instances sharing and synchronizing a common, versioned knowledge base via `cks-runtime`.
- **Domain-Specific Constraint Packs:** Pre-built sets of `OptionalConstraints` for scientific, legal, and medical domains.
- **MCP Resource Exposure:** Expose canonical knowledge structures as MCP Resources, allowing LLMs to browse and query a knowledge base directly.

---

## Version 1.2 — Knowledge Graph Traversal

**Goal:** Enable LLMs to explore the knowledge graph interactively.

- [x] **Query Subgraph:** Extract the local neighbourhood of any object, with filters and budget. Returns truncation metadata so LLMs know when they haven't seen the full picture.

## Version 1.3 — Observability & Developer Experience

**Goal:** Make the system more transparent and easier to develop against.

- [ ] **Execution Event Stream:** Expose `cks-runtime`'s Event System through the MCP server, allowing clients to subscribe to `SessionCreated`, `TransactionCommitted`, `ValidationFailed` and other events.
- [ ] **Structured Activity Logs:** Generate machine-readable logs for every tool call and internal operation.
- [ ] **Improved Error Taxonomy:** Expand structured error codes to cover all known failure modes (network errors, timeouts, schema mismatches).