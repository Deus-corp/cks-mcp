# Tools Reference

`cks-mcp` exposes **63 tools** over the Model Context Protocol. Every tool
call is a canonical operation: it runs inside a `RuntimeSession`, and any
call that mutates state does so through a `Transaction`, producing an
immutable `Version` (see [Architecture](../architecture/ARCHITECTURE.md)).

This reference is split by function, mirroring how the tools are actually
used together rather than their declaration order in the registry:

| Group | Tools | What it's for |
|-------|-------|----------------|
| [Knowledge Lifecycle](lifecycle.md) | `validate_knowledge`, `serialize_knowledge`, `explain_knowledge`, `evolve_knowledge` | Create, inspect, and change a Knowledge Structure |
| [Version Control](versioning.md) | `list_versions`, `revert_version`, `compare_versions`, `explain_diff` | Time-travel through a session's history |
| [Branching & Merging](branching.md) | `create_branch`, `merge_branch`, `merge_knowledge`, `close_session`, `fork_sandbox` | Isolate experiments and reconcile concurrent edits |
| [Graph Exploration](search-and-graph.md) | `query_subgraph`, `search_semantic`, `visualize_graph` | Retrieve and render a neighbourhood of a graph |
| [Verification & Integrity](verification.md) | `verify_source`, `detect_contradictions` | Anti-hallucination: provenance and logical consistency |
| [LLM & AI](ai-assisted.md) | `ai_chat`, `construct_knowledge`, `suggest_evolution`, `ingest_document`, `request_enrichment`, `get_llm_status`, `list_llm_models` | AI chat with tool calling, knowledge construction from text/URL, LLM provider status, and available models |
| [Export & Observability](export-and-audit.md) | `export_knowledge`, `export_session`, `get_metrics`, `export_storage`, `import_storage`, `migrate_storage`, `list_plugins` | Get data out, back up, migrate between backends, list installed plugins, and see how the server is performing |
| [Memory & Persistence](export-and-audit.md) | `register_graph`, `get_graph`, `list_graphs`, `search_graphs`, `check_graph_freshness`, `check_component_versions`, `update_registered_graph`, `explain_graph`, `check_graph_health` | Save and reuse Knowledge Graphs, check component freshness, update outdated graphs, generate reports, compute health scores |
| [Gossip & Conflict Resolution](gossip-and-conflicts.md) | `list_gossip_conflicts`, `list_inference_conflicts`, `arbitrate_inference_conflict`, `resolve_gossip_conflict`, `refresh_verification`, `resolve_temporal_conflict`, `resolve_contradiction`, `review_dead_letter`, `approve_resolution`, `reject_resolution`, `claim_conflict_task`, `complete_conflict_task`, `fail_conflict_task`, `dead_letter_conflict_task`, `list_dead_lettered_conflicts` | Drain and resolve conflicts escalated by gossip, inference, provenance, temporal, or contradiction staleness, plus the critic‑agent task lifecycle and human-in-the-loop dead-letter review |
| Agent Observability | `list_agents`, `agent_status`, `list_processes`, `process_status` | Monitor background sweepers and standalone agent processes |
| Agent Control | `start_agent`, `stop_agent`, `request_process_stop` | Start/stop in‑process sweepers and request graceful shutdown of standalone agents |
| AI Chat | `ai_chat` | Send a chat turn to an LLM that can call MCP tools [AI Chat](ai-chat.md) |

## Conventions used across every tool

- **`session_id`** — nearly every tool accepts or returns one. A session is
  created by the first call that needs to persist something
  (`validate_knowledge`, `evolve_knowledge`, `construct_knowledge`, ...);
  pass the returned `session_id` to every subsequent call that should act on
  the *same* structure instead of a fresh one.
- **Read vs. write** — `serialize_knowledge`, `explain_knowledge`,
  `query_subgraph`, `search_semantic`, `visualize_graph`,
  `detect_contradictions`, `compare_versions`, `explain_diff`,
  `suggest_evolution` (without `operations`), `list_versions`,
  `get_metrics`, `list_gossip_conflicts`, `list_inference_conflicts`,
  `list_dead_lettered_conflicts` never create a new version. The
  critic‑agent tools (`claim_conflict_task`, `complete_conflict_task`,
  `fail_conflict_task`, `dead_letter_conflict_task`) modify outbox state
  but never touch sessions or versions.
- **Dry-run before commit** — `evolve_knowledge`, `merge_branch`,
  `merge_knowledge`, and `fork_sandbox` (when given `operations`) all
  validate the *prospective* result — including a provenance check — before
  ever opening a transaction. Nothing partially-invalid is ever committed.
- **Errors** — a failed call returns a plain JSON object with an `"error"`
  code and a human-readable `"message"`, never a protocol-level exception.
  Common codes: `missing_parameter`, `session_not_found`, `invalid_json`,
  `unknown_extension`, `unsafe_url`, `validation_failed`.
- **The `json_data` fallback path** — `validate_knowledge`,
  `serialize_knowledge`, `explain_knowledge`, `evolve_knowledge`, and
  `detect_contradictions` all accept a raw `json_data` string as an
  alternative to `session_id`, for one-off calls that don't need a
  persisted session. Every one of these paths is provenance-gated exactly
  like the `session_id` path — see [Verification & Integrity](verification.md).

See also: [Extension Model](../extensions.md) for the opt-in
`extensions` parameter accepted by `validate_knowledge`.