# AI-Assisted & Ingestion

Tools that turn something unstructured — free text or a web page — into a
validated Knowledge Structure, and one that helps an LLM propose a correct
`evolve_knowledge` call instead of guessing.

## `construct_knowledge`

Sends free‑form text to an LLM (a local Ollama model **by default**,
or the Anthropic API if `CKS_LLM_PROVIDER=anthropic`), asks it to
extract entities and relationships as CKS JSON, then parses and
validates that output with `cks‑core` before persisting it as a new
session. **Nothing is committed if the LLM's output fails validation.**

**No API key is needed** when a local Ollama server is reachable
(default) — `construct_knowledge` auto‑detects it and uses `llama3.2`.
Set `CKS_LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` to use the
Anthropic API instead.

**Requires** `ANTHROPIC_API_KEY` in the server's environment.

**Parameters**

| Name | Type | Required | Description |
|------|------|----------|--------------|
| `text` | string | yes | Free-form text to extract a structure from. |
| `hint` | string | no | Focus the extraction, e.g. `"focus on causal relations between diseases and symptoms"`. |
| `model` | string | no | Model name for whichever provider is selected (e.g. an Ollama model tag, or an Anthropic model). Defaults to `CKS_OLLAMA_MODEL` / `CKS_LLM_MODEL` depending on provider. |
| `max_tokens` | integer | no | Defaults to `CKS_LLM_MAX_TOKENS` env var, or `4096`. |

**Response**

```json
{
  "constructed": true,
  "session_id": "sess-abc123",
  "version_id": "v-1",
  "serialized": "<canonical JSON>",
  "objects_count": 4,
  "relations_count": 2,
  "model_used": "claude-sonnet-4-6"
}
```

On failure, one of `llm_output_parse_error` (the model's output wasn't
valid/extractable JSON), `cks_parse_error` (JSON but not a valid CKS
document), or `validation_failed` (parsed fine, failed `cks-core`
validation) is returned, along with the raw output for debugging.

## `suggest_evolution`

Two modes in one tool, both without ever committing anything:

1. **No `operations` given** — inspects the session and returns its
   current objects/relations plus a guide to the six operator types, so an
   LLM can construct a correct `operations` list instead of guessing at the
   shape.
2. **`operations` given** — dry-runs that candidate list exactly the way
   `evolve_knowledge` does internally (including the provenance check) and
   reports whether it *would* apply cleanly, without committing. Use this
   to catch a mistake before spending a real `evolve_knowledge` call (and a
   real version) on a guess.

**Parameters:** `session_id` (required), `description` (required — what you
want to change), `operations` (optional — a candidate list to preview).

**Response, template mode**

```json
{
  "description": "add a new Concept about photosynthesis",
  "current_objects": [{"id": "obj-1", "type": "Definition", "name": "Chlorophyll"}],
  "current_relations": [],
  "available_operation_types": ["add_object — requires ...", "..."],
  "guidance": "Based on the description above and the current objects/relations listed, construct a JSON list of operations. Call this same tool again with that list as 'operations' to preview it (no commit), or pass it directly to evolve_knowledge to apply it."
}
```

**Response, preview mode**

```json
{
  "session_id": "sess-abc123",
  "would_apply": true,
  "operations_previewed": 1,
  "diagnostics": [],
  "note": "This is a preview only -- nothing has been committed. Call evolve_knowledge with the same 'operations' to apply them.",
  "preview_serialized": "<canonical JSON of the prospective result>"
}
```

## `ingest_document`

Fetches a public URL, extracts its title, meta description, and top
keywords, and returns a Knowledge Structure representing the document — a
`Document` object linked via `mentions` relations to a `Topic` object per
keyword. Uses the same SSRF/DNS-rebinding protection as `verify_source`.

**Parameters:** `url` (string, required).

**Response**

```json
{
  "url": "https://example.com/article",
  "title": "Article Title",
  "keywords": ["photosynthesis", "chlorophyll", "sunlight"],
  "knowledge_structure": "<canonical JSON>",
  "object_count": 4,
  "relation_count": 3
}
```

This builds a structure but does **not** persist it as a session by
itself — pipe `knowledge_structure` into `validate_knowledge`'s `json_data`
if you want it tracked with version history from here on.
