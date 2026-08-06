# Export & Observability

Getting data out of a session, in the format the destination expects — and
seeing how the server itself is performing.

## `export_knowledge`

Converts a session's **current** structure to an external interchange
format for use with other tools (Protégé, Neo4j, triple stores).

**Parameters:** `session_id` (required), `format` (optional — one of
`"json-ld"` (default), `"turtle"`, `"rdf-xml"`).

**Response:** `{"format": "json-ld", "data": "<converted document>"}`.

## `export_session`

Packages a full session bundle for migration or archival — the current
structure, the complete version history, and session metadata. This is a
different job from `export_knowledge`: that one *converts format*, this one
*preserves everything needed to reconstruct the session elsewhere*.

**Parameters**

| Name | Type | Required | Description |
|------|------|----------|--------------|
| `session_id` | string | yes | Session to export. |
| `format` | string | no | `"bundle"` (default) — full migration envelope with version history. `"cks"` — bare canonical CKS JSON of the current structure only (equivalent to `serialize_knowledge`). |
| `include_structures` | boolean | no | When `true` and `format="bundle"`, embed the full serialized structure for *every* historical version (can be large for long-lived sessions). Default `false` — only version metadata (id, timestamp, state hash) is included. |

**Response (`format="bundle"`)**

```json
{
  "format": "bundle",
  "session_id": "sess-abc123",
  "bundle": {
    "cks_mcp_export": true,
    "schema_version": "1.0",
    "session": {"session_id": "...", "parent_session_id": null, "parent_version_id": null, "closed": false, "metadata": {}},
    "current_structure": {"root_hash": "...", "objects_count": 4, "relations_count": 2, "cks_json": "<canonical JSON>"},
    "version_history": {"count": 2, "include_structures": false, "versions": [{"version_id": "v-1", "transaction_id": "tx-1", "created_at": "...", "state_hash": "..."}]}
  },
  "bundle_json": "<the same bundle as a raw JSON string, ready to write to disk>"
}
```

A bundle can be reimported elsewhere by feeding its `cks_json` (or a
version's `cks_json`, if `include_structures` was set) into
`validate_knowledge`.

## `get_metrics`

Returns two independent dashboards: runtime-level operation metrics from
`cks-runtime`, and per-tool call telemetry collected by `cks-mcp` itself.

**Parameters:** none.

**Response**

```json
{
  "runtime_metrics": {
    "operation_counts": {"validate": 12, "evolve": 5},
    "average_execution_times": {"validate": 0.004, "evolve": 0.011}
  },
  "tool_telemetry": {
    "validate_knowledge": {"calls": 12, "success_rate": 1.0, "p50_ms": 3.1, "p95_ms": 9.8, "p99_ms": 14.2, "top_errors": []},
    "evolve_knowledge": {"calls": 5, "success_rate": 0.8, "p50_ms": 8.0, "p95_ms": 20.1, "p99_ms": 22.0, "top_errors": ["invalid_operations"]}
  }
}
```

`tool_telemetry` is scoped to the current server process — it resets on
restart. Use it to spot which tool is slow or erroring most often across a
session, not as a durable audit log (for that, see `list_versions` and
`export_session`).

## `register_graph`

Saves a named reference to an existing session's Knowledge Graph,
allowing it to be found and reused later via `get_graph`.

**Parameters:** `name` (required), `session_id` (required),
`description` (optional), `tags` (optional, comma-separated), `public`
(optional boolean, default `false` — opts the graph into the gallery,
discoverable by other callers via `list_graphs(public_only=true)` /
`search_graphs`, not just by name).

**Response:** `{"registered": true, "name": "my-graph", "public": false}`.

## `get_graph`

Looks up a previously registered graph by name and returns its `session_id`
and metadata, or `{"found": false}` if no graph is registered under that name.

**Parameters:** `name` (required).

**Response:** `{"found": true, "name": "my-graph", "session_id": "...", "description": "...", "tags": "...", "public": false, "created_at": "...", "updated_at": "..."}`.

## `list_graphs`

Lists every registered graph, most recently updated first.
Optionally filter to graphs whose tags contain a given substring,
and/or restrict to public graphs only (the gallery).

**Parameters:** `tag` (optional), `public_only` (optional boolean, default `false`).

**Response:** `{"graphs": [{"name": "my-graph", "session_id": "...", "public": false, ...}, ...]}`.

## `search_graphs`

Free-text search over registered graphs, matched case-insensitively
against each graph's `name`, `description`, and `tags`. Use this to
discover a graph to resume with `get_graph` when you don't already
know its exact name.

**Parameters:** `query` (required), `tag` (optional, further narrows by
exact/substring tag), `public_only` (optional boolean, default `false`).

**Response:** `{"graphs": [{"name": "my-graph", "session_id": "...", ...}, ...]}`.

## `check_graph_freshness`

Read-only check of whether a registered graph is still fresh, using
the same TTL `GraphFreshnessSweeper` (cks-runtime) applies in the
background (`graph_freshness_ttl_seconds` in `RuntimeConfig`, default
7 days). Does not refresh the graph itself — a stale graph is left for
a future update agent to act on (cks-runtime enqueues a
`graph_outdated` outbox task for it independently, on the same TTL).

**Parameters:** `name` (required).

**Response:** `{"fresh": true}` when within the TTL, or
`{"fresh": false, "last_updated": "...", "ttl_days": 7.0}` when
outdated. `{"found": false}` if no graph is registered under that
name.

## `check_graph_health`

Computes an aggregate health score (0.0–1.0) for a registered graph by
combining five read-only checks into one weighted metric: version freshness
(weight 0.3), TTL freshness (weight 0.1), contradictions (weight 0.3),
verification coverage (weight 0.2), and dead‑lettered conflict tasks
(weight 0.1). Read-only — does not modify the graph.

**Parameters:** `name` (required — registered graph name).

**Response:** `{"name": "cks-ecosystem", "session_id": "...", "health_score": 0.85, "metrics": {...}, "timestamp": "..."}`.

## `explain_graph`

Generates a human-readable Markdown report for any registered graph,
grouping entities by type (Component, Module, Sweeper, Agent, Tool,
ADR, Plugin) and showing their relations. Makes knowledge graphs
accessible to any LLM or person without parsing raw JSON.

**Parameters:** `name` (required — registered graph name).

**Response:** `{"found": true, "name": "cks-ecosystem", "session_id": "...", "report": "<markdown text>"}`.

## `export_storage`

Exports a complete dump of all sessions, versions, graph registry entries,
embeddings, and pending/failed outbox tasks to a JSON file. Returns the file
path and a summary of what was exported. This is the foundation for backup
and migration workflows (ADR-012).

**Parameters:** `output_path` (optional — path for the dump file; defaults to
a temp file).

**Response:** `{"output_path": "...", "summary": {"sessions": N, "versions": N, "graphs": N, "embeddings": N, "outbox": N}}`.

## `import_storage`

Restores data from a previously exported dump file into the current storage
backend. Supports two modes:
- `clear` — deletes all existing data before importing.
- `merge` — adds/updates data alongside existing records (default).

**Parameters:** `file_path` (required), `mode` (optional, `"merge"` by default).

**Response:** `{"imported": true, "mode": "merge", "summary": {...}}`.

## `migrate_storage`

Transfers all data from the current storage backend to a new backend of a
different type (e.g. SQLite → Postgres). Exports from the current backend,
creates a new target backend, and imports the data. Returns the path or DSN
of the new storage. Does **not** replace the active `runtime.storage` — the
caller must restart the server pointing at the new backend.

**Parameters:** `target_backend` (required, `"sqlite"` or `"postgres"`),
`target_path` (required — file path for SQLite, connection string for Postgres).

**Response:** `{"migrated": true, "target_backend": "sqlite", "target_path": "...", "summary": {...}}`.