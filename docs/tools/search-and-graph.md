# Graph Exploration & Visualization

Retrieving and rendering a neighbourhood of a Knowledge Structure, rather
than the whole thing — important once a session's graph grows past what
fits comfortably in a response.

## `query_subgraph`

Extracts the local k-hop neighbourhood around one or more seed object ids.
Read-only. This is the workhorse the other two tools in this group are
built on.

**Parameters**

| Name | Type | Required | Description |
|------|------|----------|--------------|
| `session_id` | string | yes | Session to query. |
| `seed_ids` | string[] | yes | Object ids to start traversal from. |
| `depth` | integer | no | Max hops from any seed. Default `1`. |
| `include_relation_types` | string[] | no | Only traverse/include these relation types. |
| `include_object_types` | string[] | no | Only include discovered objects of these types (seeds are always kept). |
| `max_tokens` | integer | no | Approximate token budget for the result. |
| `max_objects` | integer | no | Hard cap on total objects returned. |
| `type_weights` | object | no | Object type → weight (float), used to prioritise what survives when the budget forces truncation. |
| `compact_mode` | boolean | no | Return `{"nodes": [...], "edges": [...]}` instead of full canonical JSON. |
| `structure_filters` | object | no | AND-filter on non-relation objects' `structure` fields after extraction — e.g. `{"status": "active"}`. Seeds are always kept regardless of the filter; a relation survives only if both its participants do. |

**Response (full mode)**

```json
{
  "session_id": "sess-abc123",
  "subgraph": "<canonical JSON of the extracted neighbourhood>",
  "subgraph_root_hash": "...",
  "total_found_nodes": 12,
  "returned_nodes": 8,
  "is_truncated": true,
  "truncation_reason": "max_objects",
  "suggested_next_seed": "obj-9"
}
```

With `compact_mode: true`, `subgraph` becomes
`{"nodes": [{"id", "type", "name", "props"}], "edges": [{"source", "target", "type"}]}`
— cheaper to consume than full canonical JSON when you only need the
shape of the graph. When truncated, `suggested_next_seed` gives you an id
to continue traversal from in a follow-up call.

## `search_semantic`

Semantic search over a session: given a natural-language `query`, finds
relevant seed objects by meaning (via HuggingFace embeddings generated in
the background by `cks-runtime`'s outbox worker) and expands the
neighbourhood around them using `query_subgraph`.

**Parameters**

| Name | Type | Required | Description |
|------|------|----------|--------------|
| `session_id` | string | yes | Session to search in. |
| `query` | string | yes | Natural-language description of what to find. |
| `seed_ids` | string[] | no | Skip vector search and expand from these ids directly. Also the fallback if no embeddings exist yet for this session. |
| `top_k` | integer | no | Max seed objects to use. Default `3`. |
| `depth` | integer | no | Hops to expand around each seed. Default `1`. |
| `min_score` | number | no | Minimum cosine similarity (0.0–1.0). Default `0.0` (no filtering). |

**Response**

```json
{
  "status": "success",
  "matched_seeds": ["obj-3", "obj-7"],
  "subgraph": {"nodes": [...], "edges": [...]},
  "meta": {"total_found_nodes": 5, "returned_nodes": 5, "is_truncated": false, "suggested_next_seed": null},
  "min_score": 0.3,
  "scores": {"obj-3": 0.81, "obj-7": 0.64}
}
```

`scores` is present only when the match came from vector search (not from
explicit `seed_ids`). Requires `HF_TOKEN` to be set for the embedding
client — without it (or before any embeddings have been generated for a
session), pass `seed_ids` explicitly as a fallback.

## `visualize_graph`

Exports a session's structure (or a subgraph of it) as a Mermaid diagram —
most MCP clients, including Claude Desktop, render Mermaid natively.

**Parameters:** `session_id` (required), `seed_ids` (optional — defaults to
every object in the session), `depth` (default `1`; ignored, treated as `0`,
when `seed_ids` is omitted), `max_objects` (default `20`).

**Response**

```json
{
  "mermaid": "graph TD\n    n0[\"Photosynthesis (Definition)\"]\n    n1[\"Chlorophyll (Definition)\"]\n    n0 -->|\"requires\"| n1",
  "total_found_nodes": 2,
  "returned_nodes": 2,
  "is_truncated": false
}
```

Internally this always routes through `query_subgraph` in compact mode, so
its truncation and budget semantics are identical — use `query_subgraph`
first if you need to tune `structure_filters` or `type_weights` before
visualizing.
