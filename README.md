# CKS MCP Server

> Model Context Protocol server for Canonical Knowledge Structure.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-1147%20passed%2C%206%20skipped-brightgreen)
[![PyPI](https://img.shields.io/pypi/v/cks-mcp)](https://pypi.org/project/cks-mcp/)

> 🚀 **[Live demo →](https://punctumactus.github.io/cks-website/demo/demo.html)** — explore the CKS ecosystem graph directly in your browser, no server required.

`cks-mcp` is a fully asynchronous MCP (Model Context Protocol) server
that gives LLMs a **canonical knowledge backbone**. It exposes **71
tools** (listed under *Available Tools* below) for validation, evolution,
branching, merging, semantic search, contradiction detection, sandboxing,
and more, backed by the deterministic, immutable semantics of `cks-core`
and the async operational management of `cks-runtime`.

Every tool call creates a **Runtime Session** and **Transaction**,
producing an immutable **Version** and collecting **Diagnostics**.
This guarantees full auditability and reproducibility.

---

# Ecosystem

Other projects build upon it:

| Project | Description | Repository |
|---------|-------------|------------|
| **cks-core** | Canonical semantic engine – the single source of canonical truth. | [cks-core](https://github.com/PunctumActus/cks-core) |
| **cks-runtime** | Operational environment – sessions, transactions, persistence. | [cks-runtime](https://github.com/PunctumActus/cks-runtime) |
| **cks-mcp** | MCP server – exposes CKS to LLMs and autonomous agents. | [cks-mcp](https://github.com/PunctumActus/cks-mcp) |
| **cks-studio** | Visual workspace – explore, monitor, and manage graphs. | [cks-studio](https://github.com/PunctumActus/cks-studio) |
| **cks-website** | Documentation & demo site. | [cks-website](https://github.com/PunctumActus/cks-website) |

📖 **Full documentation, case studies, and an interactive demo**
are available at the **[CKS Documentation Site](https://punctumactus.github.io/cks-website/)**.

---

# Quick Start

1. Install and connect to Claude Desktop (see [Installation](#installation)).
2. (Optional) Semantic search works out of the box with the built-in
   `fastembed` engine (no API keys required). To use HuggingFace
   models instead, set `CKS_EMBEDDING_PROVIDER=huggingface` and
   `export HF_TOKEN=hf_...`. See [Getting Started](docs/getting-started.md).
3. In the chat, start your message with **"Use cks-mcp to…"**.
4. Claude automatically picks the right tool from the 71 available — validation, evolution, branching, merging, source verification, contradiction detection, semantic search, subgraph queries, sandboxing, and more.
5. Every operation is logged, versioned, and stored in a persistent SQLite database.

**Just type "Use cks-mcp to..." and Claude does the rest. That's it.**
**No programming, no command line — just a conversation!**

![CKS Demo](https://github.com/PunctumActus/cks-mcp/releases/download/v1.10.2/demo.gif)

*In the video above, Claude creates a validated knowledge graph about the water cycle from a single sentence, using `validate_knowledge` and `explain_knowledge`. All 71 tools are ready for you: branching, merging, versioning, source verification, contradiction detection, subgraph queries, sandboxing, gossip conflict resolution, and more — all triggered by plain English.*

---

# Why cks-mcp?

LLMs generate plausible but unverified statements. `cks-mcp` gives them
a **canonical knowledge backbone**: every piece of information must be
explicitly structured, validated against formal constraints, and
traceable to its origin.

- **Eliminate citation hallucinations** — optional extensions like
  `embedding_projection` mechanically detect references to non-existent
  sources.
- **Ensure verification integrity** — the `verify_source` tool performs
  a real HTTP check and cryptographically signs the result. Any
  `VerificationRecord` without a valid signature is automatically
  rejected, even if the model fails to request the check.
- **Semantic search with real embeddings** — the `search_semantic` tool uses HuggingFace models to find relevant nodes by meaning, not just keywords. A query for "how to train AI models" returns "Gradient Descent" and "Neural Network", not "Banana".
- **Graph-based RAG** — combine semantic search with `query_subgraph` to retrieve a full neighbourhood around the found concepts, giving the LLM the context it needs without hallucinating connections.
- **Full audit trail** — every operation is captured in an immutable
  version history, providing complete accountability for AI-generated
  knowledge.
- **Time-travel debugging** — `list_versions`, `revert_version`, and `compare_versions` give LLMs a full version-control system for knowledge, enabling safe rollbacks and change inspection.
- **Contradiction detection** — `detect_contradictions` flags mutual exclusions (e.g., both `supports` and `contradicts` between the same pair) and functional relation violations (e.g., a planet orbiting two different stars).
- **Hypothesis sandboxing** — `fork_sandbox` creates an isolated branch, optionally applies a hypothesis, and reports the diff from the fork point — all without touching the parent session. Safe to discard or promote.
- **Content ingestion** — `ingest_document` fetches a public URL, extracts structured content (sections, tables, lists, JSON‑LD/OpenGraph metadata) and builds a Knowledge Structure with Document, Section, Table, List, Metadata, and Topic objects. An optional `use_llm` parameter sends the extracted data to an LLM (same provider auto‑selection as `construct_knowledge`) for a richer, model‑generated graph.
- **LLM-assisted knowledge construction** — `construct_knowledge` converts free-form text into a validated Knowledge Structure using a local Ollama model (no API key needed), the Anthropic API, Google Gemini, or any OpenAI-compatible endpoint, selected via `CKS_LLM_PROVIDER` (`auto` picks Ollama or Anthropic; `google`/`openai_compatible` must be selected explicitly).
- **Session portability** — `export_session` packages a full session bundle (structure + version history) for migration or archival.
- **Telemetry dashboard** — `get_metrics` now returns per‑tool latency percentiles (p50/p95/p99), success rates, and top error types since server start.
- **Multi‑agent pipelines** — the `CKSAgentOrchestrator` (ADR‑007) chains
  specialised agents (Researcher → Critic → Synthesizer → Arbiter) that
  communicate through the persistent outbox and CRDT registers. Agents
  run autonomously as a pipeline, with each step's findings committed as
  immutable knowledge objects. Start a pipeline via the
  `cks-pipeline-agent` console script.
- **AI Chat with tool calling** — the `ai_chat` tool lets an LLM (Ollama or Anthropic) call any safe MCP tool, scoped to a session, enabling autonomous graph exploration and evolution.

---

# Installation

```bash
pip install cks-mcp
```

The server requires `cks-runtime` (which includes `cks-core`) as a dependency.

See [Getting Started](docs/getting-started.md#optional-environment-variables)
for the full list of environment variables and how to set them via a
`~/.cks-mcp/.env` file.

---

# Connect to Claude Desktop

1. Install all three packages into a single virtual environment:
   ```bash
   python3 -m venv cks-env
   source cks-env/bin/activate
   pip install cks-core cks-runtime cks-mcp
   ```

2. Open Claude Desktop, go to **Settings → Developer → Edit Config**.
   The configuration file (`claude_desktop_config.json`) will open.
   Add the following block (adjust the path to your `cks-mcp` executable):
   ```json
   {
     "mcpServers": {
       "cks-mcp": {
         "command": "/absolute/path/to/cks-env/bin/cks-mcp"
       }
     }
   }
   ```

3. Save the file and fully restart Claude Desktop (Cmd+Q, then reopen).
   After restart, a connector icon will appear – `cks-mcp` with 71 tools is ready to use.

See [Getting Started](docs/getting-started.md) for a walkthrough of your
first session once the server is connected.

---

# HTTP Transport & Real-Time Events

Setting `CKS_MCP_HTTP_PORT` starts an optional `aiohttp` server
alongside the default stdio transport (used e.g. by `cks-studio` running
in a browser):

```bash
CKS_MCP_HTTP_PORT=8769 cks-mcp
```

- `POST /mcp` — the same JSON-RPC surface as stdio, over HTTP.
- `GET /events` / `GET /events/{session_id}` — a Server-Sent Events
  (SSE) stream of runtime lifecycle events (`SessionCreated`,
  `VersionCreated`, `TransactionCommitted`, `GossipConflictDetected`,
  `CRDTForkDetected`, and more), so a client can react live instead of
  polling. Supports an optional `?event_types=A,B` filter. Each line is
  `data: {"event": "...", "session_id": "...", "timestamp": "...", "detail": {...}}`.

By default this transport has no authentication and is meant for
local development / trusted networks. Setting `CKS_MCP_HTTP_TOKEN`
requires a matching token on every request to `/mcp` and `/events`,
either as `Authorization: Bearer <token>` or, for browser
`EventSource` clients (which can't set custom headers), as a
`?token=<token>` query parameter:

```bash
CKS_MCP_HTTP_PORT=8769 CKS_MCP_HTTP_TOKEN=change-me cks-mcp
```

```
GET /events?token=change-me
```

See [HTTP Transport security notes](docs/security.md#optional-http-transport)
for details.

---

# Available Tools

71 tools, grouped by function. Full reference with parameters and
real request/response examples: [`docs/tools/`](docs/tools/index.md).

| Group | Tools |
|-------|-------|
| Knowledge Lifecycle | `validate_knowledge`, `serialize_knowledge`, `explain_knowledge`, `evolve_knowledge` |
| Version Control | `list_versions`, `revert_version`, `compare_versions`, `explain_diff` |
| Branching & Merging | `create_branch`, `merge_branch`, `merge_knowledge`, `close_session`, `fork_sandbox` |
| Graph Exploration | `query_subgraph`, `search_semantic`, `visualize_graph` |
| Verification & Integrity | `verify_source`, `detect_contradictions` |
| LLM & AI | `ai_chat`, `construct_knowledge`, `suggest_evolution`, `ingest_document`, `request_enrichment`, `get_llm_status`, `list_llm_models` |
| Export & Observability | `export_knowledge`, `export_session`, `get_metrics`, `export_storage`, `import_storage`, `migrate_storage`, `list_plugins` |
| Memory & Persistence | `register_graph`, `get_graph`, `clone_graph`, `list_graphs`, `search_graphs`, `check_graph_freshness`, `check_component_versions`, `update_registered_graph`, `update_graph_lifecycle`, `explain_graph`, `check_graph_health`, `compare_graphs`, `merge_graphs`, `link_graphs` |
| Gossip & Conflict Resolution | `list_gossip_conflicts`, `list_inference_conflicts`, `arbitrate_inference_conflict`, `resolve_gossip_conflict`, `refresh_verification`, `resolve_temporal_conflict`, `resolve_contradiction`, `review_dead_letter`, `approve_resolution`, `reject_resolution`, `claim_conflict_task`, `complete_conflict_task`, `fail_conflict_task`, `dead_letter_conflict_task`, `list_dead_lettered_conflicts` |
| Agent Observability | `list_agents`, `agent_status`, `list_processes`, `process_status` |
| Agent Control | `start_agent`, `stop_agent`, `request_process_stop`, `start_pipeline`, `list_pipeline_runs` |

## Critic Agent (unattended conflict resolution)

Alongside the interactive tools above, `cks-critic-agent` is a separate console
script that runs autonomously: it polls the persistent outbox (SQLite/Postgres
only — not the default in-memory backend) for `gossip_conflict` and
`inference_conflict` tasks, resolves each via `merge_branch` /
`arbitrate_inference_conflict(auto_resolve=True)`, and dead-letters whatever it
can't confidently resolve for a human to review via
`list_dead_lettered_conflicts`.
- `provenance_conflict` → calls `refresh_verification` to re‑verify the source.
- `temporal_conflict` → calls `resolve_temporal_conflict(action="bump", extend_by_days=30)` as a safe default.

```bash
# Point it at the same database cks-mcp itself uses (defaults to
# ~/.cks-mcp/cks_mcp.db if CKS_MCP_DB_PATH is unset).
CKS_MCP_DB_PATH=~/.cks-mcp/cks_mcp.db cks-critic-agent
```

Env vars: `CKS_MCP_DB_PATH` (shared storage path), `CKS_CRITIC_POLL_INTERVAL`
(seconds between polls, default 5), `CKS_CRITIC_MAX_RETRIES` (attempts before
dead-lettering, default 5). See `cks_mcp/critic_agent.py` for the resolution
policy in full.

## Enrichment Agent (external RAG / auto‑growth)

`cks-enrichment-agent` is a companion process that searches external sources
(Wikipedia, arXiv) for more context about an object marked for enrichment
(via `request_enrichment`) and links whatever it finds back into the graph
with provenance. Same outbox‑polling architecture as the Critic Agent —
runs autonomously against the same database.

```bash
CKS_MCP_DB_PATH=~/.cks-mcp/cks_mcp.db cks-enrichment-agent
```

Env vars: `CKS_MCP_DB_PATH` (shared storage), `CKS_ENRICHMENT_POLL_INTERVAL`
(default 5s), `CKS_ENRICHMENT_MAX_RETRIES` (default 5), `CKS_ENRICHMENT_MIN_SCORE`
(default 0.5), and adapter‑specific tuning (see `cks_mcp/enrichment_agent.py`).

## Fork Resolution Agent (autonomous CRDT fork resolution)

`cks-fork-agent` is a companion process, following the same outbox‑polling
architecture as the Critic Agent and Enrichment Agent, dedicated to resolving
`crdt_fork` tasks (MV‑Register forks detected by `CRDTForkDetected`,
cks‑runtime ADR‑013 Stage 2) without human involvement. It is purely
mechanical — no LLM is involved:

1. Prefers the causally‑newest conflicting object, when `VersionVector`
   comparison (`causality_check`) shows one candidate strictly dominates the
   others.
2. Otherwise falls back to whichever candidate has the most recent
   `created_at` on the live MV‑Register pointer row.
3. Otherwise falls back to a deterministic, replica‑agnostic tie‑break: the
   alphabetically‑first `object_id` — every replica computes object ids
   identically (content hashes), so every replica's agent converges on the
   same winner independently.

```bash
CKS_MCP_DB_PATH=~/.cks-mcp/cks_mcp.db cks-fork-agent
```

Env vars: `CKS_MCP_DB_PATH` (shared storage path), `CKS_FORK_AGENT_POLL_INTERVAL`
(seconds between polls, default 30), `CKS_FORK_AGENT_MAX_RETRIES` (attempts
before dead‑lettering, default 3), `CKS_FORK_AGENT_HEARTBEAT_INTERVAL` (lease
renewal interval, default 69). See `cks_mcp/fork_resolution_agent.py` for the
resolution policy in full.

> **Note:** `critic_agent.py` also claims `crdt_fork` tasks from the same
> outbox queue, with a different (simpler, lexicographically‑last) tie‑break
> policy. Both agents compete for the same queue if run together — whichever
> claims a fork first decides its outcome. Run `cks-fork-agent` as the
> intended owner of `crdt_fork` resolution; avoid running both against the
> same database at once.

## Pipeline Agent (multi‑agent orchestration)

`cks-pipeline-agent` is a console script that runs a configurable pipeline of
`AgentStep` implementations coordinated by `CKSAgentOrchestrator`. Each step
writes its result as a knowledge object (with provenance and a semantic edge
from the previous step), and the orchestrator publishes `AgentStepStarted` /
`AgentStepCompleted` events. Built on the same outbox‑polling architecture as
the other autonomous agents.

```bash
CKS_MCP_DB_PATH=~/.cks-mcp/cks_mcp.db cks-pipeline-agent
```

Env vars: `CKS_MCP_DB_PATH` (shared storage path), `CKS_PIPELINE_POLL_INTERVAL`
(default 5s), `CKS_PIPELINE_MAX_RETRIES` (default 5). See
`cks_mcp/orchestrator.py` and `cks_mcp/pipeline/researcher_step.py` /
`reviewer_step.py` for the pipeline and step implementations.

---

# Usage Examples

A couple of representative calls — the full set, with real response
shapes for every tool, is in [`docs/tools/`](docs/tools/index.md).

## Validate a structure

```json
{
  "method": "tools/call",
  "params": {
    "name": "validate_knowledge",
    "arguments": {
      "json_data": "{\"objects\":[{\"identity\":{\"id\":\"obj-1\",\"type\":\"Definition\",\"name\":\"Test\"},\"structure\":{}}]}"
    }
  }
}
```

The response includes `valid`, `session_id`, `version_id`, and
`diagnostics` — keep `session_id` for every following call on this
structure. See [Knowledge Lifecycle](docs/tools/lifecycle.md) for the
other three tools in this group.

## Semantic search (no seed IDs required)

```json
{
  "method": "tools/call",
  "params": {
    "name": "search_semantic",
    "arguments": {"session_id": "...", "query": "virtual machines in the cloud"}
  }
}
```

Returns matched objects by meaning (e.g. `EC2`, not `S3`), expanded into a
subgraph. See [Graph Exploration](docs/tools/search-and-graph.md).

## Branch, evolve independently, and merge back

```json
{"method": "tools/call", "params": {"name": "create_branch", "arguments": {"session_id": "trunk-session-id"}}}
```
```json
{"method": "tools/call", "params": {"name": "evolve_knowledge", "arguments": {"session_id": "branch-session-id", "operations": [...]}}}
```
```json
{"method": "tools/call", "params": {"name": "merge_branch", "arguments": {"target_session_id": "trunk-session-id", "source_session_id": "branch-session-id"}}}
```

A successful merge commits a new version and returns the merged
structure; a conflicting merge returns `"merged": false` with a
`conflicts` list to resolve. See
[Branching & Merging](docs/tools/branching.md) for the full
conflict-resolution flow.

## Detect contradictions

```json
{
  "method": "tools/call",
  "params": {
    "name": "detect_contradictions",
    "arguments": {"session_id": "..."}
  }
}
```

Requires `MutualExclusionRule` and/or `FunctionalRelationRule` objects in
the structure declaring which relation types to check. See
[Verification & Integrity](docs/tools/verification.md) for the rule shapes
and how this interacts with `verify_source`'s provenance signing.

---

# Security and Provenance

`verify_source` includes built-in protections:
- **SSRF prevention**: URLs are validated against a strict allowlist;
  private, loopback, and cloud metadata IPs are blocked. DNS rebinding
  attacks are neutralised by pinning the connection to the IP address
  resolved during the safety check.
- **Cryptographic signing**: every verification record is signed with a
  process-local HMAC. `validate_knowledge` unconditionally verifies this
  signature, so a hand‑written `VerificationRecord` can never pass as
  genuine.

---

# Testing

```bash
python -m pytest -v
```

1147+ tests: 1141 passing, 6 skipped (require Postgres or optional providers not configured in a default environment).

---

# License

MIT
