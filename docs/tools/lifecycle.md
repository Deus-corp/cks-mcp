# Knowledge Lifecycle

The four core operations every other tool builds on top of. All four accept
either a fresh `json_data` string or an existing `session_id` — see
[the shared conventions](index.md#conventions-used-across-every-tool).

## `validate_knowledge`

Validates a Knowledge Structure and returns diagnostics. This is usually the
**first** call in a workflow: it both checks correctness and creates the
session that later calls (`list_versions`, `evolve_knowledge`,
`query_subgraph`, ...) will reference.

**Parameters**

| Name | Type | Required | Description |
|------|------|----------|--------------|
| `json_data` | string | yes* | A CKS Knowledge Structure as JSON. See the shape below. |
| `session_id` | string | no | Validate an existing session's current state instead of `json_data`. |
| `extensions` | string[] | no | Opt-in validation rules for this call only: `embedding_projection`, `verification_record`, `type_hierarchy`, `relation_type`, `mutual_exclusion`, `functional_relation`. See [Extension Model](../extensions.md). |

\* not required when `session_id` is given.

A Knowledge Structure is `{"objects": [...]}`, where each entry has an
`identity` (`id`, `type`, `name`) and a free-form `structure` dict. A
relation is just an object whose `structure` contains `participants` (a
list of object ids) and `relation_type`:

```json
{
  "objects": [
    {"identity": {"id": "obj-1", "type": "Definition", "name": "Photosynthesis"},
     "structure": {"content": "..."}},
    {"identity": {"id": "obj-2", "type": "Definition", "name": "Chlorophyll"},
     "structure": {"content": "..."}},
    {"identity": {"id": "rel-1", "type": "Relation", "name": "r"},
     "structure": {"participants": ["obj-1", "obj-2"], "relation_type": "requires"}}
  ]
}
```

**Response**

```json
{
  "valid": true,
  "extensions_applied": [],
  "diagnostics": [],
  "session_id": "sess-...",
  "version_id": "v-..."
}
```

`version_id` is omitted when validation fails (nothing was committed).
`diagnostics` combines two independent sources: `cks-core`'s own validation
pipeline, and an **unconditional** provenance check for any
`VerificationRecord` present in the structure — the latter runs even if you
didn't ask for the `verification_record` extension (see
[Verification & Integrity](verification.md)).

## `serialize_knowledge`

Returns the canonical JSON representation of a structure — either a fresh
`json_data` payload (round-tripped through the canonical form) or an
existing session's current state.

**Parameters:** `json_data` (string, required unless `session_id` given),
`session_id` (string, optional).

**Response:** `{"session_id": "...", "serialized": "<canonical JSON string>"}`
when called with `session_id`; the bare serialized string when called with
`json_data` directly.

## `explain_knowledge`

Produces a human-readable, structured explanation of a Knowledge Structure.
Read-only — even with `session_id`, this never creates a new version.

**Parameters:** same as `serialize_knowledge`, plus:

| Name | Type | Required | Description |
|------|------|----------|--------------|
| `object_id` | string | no | Explain *why* this one object is currently believed instead of the general structure-wide explanation: recursively walks every active `InferenceStep` chain concluding it, through each step's premises, down to base facts. |

**Response (no `object_id`):** `{"session_id": "...", "explanation": {...}}`.

**Response (with `object_id`):** `{"session_id": "...", "explanation": {"object_id": "...", "exists": true, "has_inference": true, "active_steps": [...], "superseded_steps": [...]}}`.
`exists` is whether `object_id` itself is present in the structure at all
(a dangling id doesn't stop the walk). `active_steps` is ordered by
entrenchment (confidence, descending); each entry carries `step_id`,
`operator`, `confidence`, `justification`, `alternatives_considered`, and
its own recursive `premises`. A premise that is itself a meta-citation of
another `InferenceStep` (rather than an ordinary object) is shaped
`{"object_id": "...", "cites_step": true}` instead of being recursed into.
`superseded_steps` is the belief's revision history — steps that used to
conclude this object before being superseded, each with `step_id`,
`operator`, `confidence`, `justification`, `superseded_by`. A branch that
hits a cycle or the traversal's `max_depth` is marked
`"truncated": "cycle"` or `"truncated": "max_depth"` rather than looping
or growing unbounded.

Requires an attached Core that implements the optional `explain_inference`
capability (cks-core ≥ 1.18.0 does); an unsupported Core or an unknown
`object_id` is reported as `{"error": "internal_error", "message": "..."}`
rather than an empty explanation, since there's no meaningful empty default
for "why".

## `evolve_knowledge`

Applies a sequence of structural operators to a structure and commits the
result as a new version.

**Parameters**

| Name | Type | Required | Description |
|------|------|----------|--------------|
| `json_data` | string | yes* | Base structure, if not using `session_id`. |
| `session_id` | string | no | Evolve this session's current state instead. |
| `operations` | object[] | yes | Ordered list of operators (see below). |

Each operator is `{"type": "...", ...}`; the other fields are **not**
interchangeable between types:

| `type` | Required fields | Notes |
|--------|------------------|-------|
| `add_object` | `identity`, optional `structure` | Fails if the id already exists. |
| `add_relation` | `identity`, `participants`, `relation_type`, optional `structure` | |
| `remove_object` | `object_id` | Cascades: every relation referencing it is also removed (`cascade_removed_relations` in the response lists them). |
| `remove_relation` | `relation_id` | Only valid for an id that is actually a relation. |
| `update_object` | `object_id`, `structure_patch`, optional `mode` (`"merge"` default or `"replace"`) | `merge` shallow-merges the patch; a patch value of `null` deletes that key. Leaves id/relations untouched, zero cascade. |
| `rename_object` | `object_id`, `new_name` | Changes only `identity.name`. Zero cascade, no relation rebuild. |

**Example request**

```json
{
  "session_id": "sess-abc123",
  "operations": [
    {"type": "add_object", "identity": {"id": "obj-2", "type": "Lemma", "name": "New"}, "structure": {}},
    {"type": "update_object", "object_id": "obj-1", "structure_patch": {"summary": "revised text"}}
  ]
}
```

**Response**

```json
{
  "evolved": true,
  "serialized": "<canonical JSON>",
  "operations_applied": 2,
  "version_id": "v-...",
  "session_id": "sess-abc123"
}
```

`cascade_removed_relations` is added only when a `remove_object` triggered
one. Before committing, the tool dry-runs the evolution once to check the
*prospective* structure's provenance and validity — the transaction is only
opened once both pass, so a bad `operations` list never produces a partial
or invalid version. If you're not sure your `operations` list is correct,
preview it first with [`suggest_evolution`](ai-assisted.md#suggest_evolution)
— it runs the exact same dry-run without committing.
