# Tools Reference

`cks-mcp` exposes **25 tools** over the Model Context Protocol. Every tool
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
| [AI-Assisted & Ingestion](ai-assisted.md) | `construct_knowledge`, `suggest_evolution`, `ingest_document` | From free text or a URL to a validated structure; `ingest_document` now extracts tables, lists, metadata and supports optional LLM enrichment |
| [Export & Observability](export-and-audit.md) | `export_knowledge`, `export_session`, `get_metrics` | Get data out, and see how the server is performing |
| [Gossip & Conflict Resolution](gossip-and-conflicts.md) | `list_gossip_conflicts` | Drain conflicts escalated by a background gossip cycle for a Critic agent to resolve |

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
  `get_metrics`, and `list_gossip_conflicts` never create a new version.
  Everything else does. (`list_gossip_conflicts` still has a side effect
  worth knowing about — by default it drains the records it returns from
  the conflict queue; see [Gossip & Conflict Resolution](gossip-and-conflicts.md).)
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
