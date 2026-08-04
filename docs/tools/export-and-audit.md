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
`description` (optional), `tags` (optional, comma-separated).

**Response:** `{"registered": true, "name": "my-graph"}`.

## `get_graph`

Looks up a previously registered graph by name and returns its `session_id`
and metadata, or `{"found": false}` if no graph is registered under that name.

**Parameters:** `name` (required).

**Response:** `{"found": true, "name": "my-graph", "session_id": "...", "description": "...", "tags": "...", "created_at": "...", "updated_at": "..."}`.

## `list_graphs`

Lists every registered graph, most recently updated first.
Optionally filter to graphs whose tags contain a given substring.

**Parameters:** `tag` (optional).

**Response:** `{"graphs": [{"name": "my-graph", "session_id": "...", ...}, ...]}`.