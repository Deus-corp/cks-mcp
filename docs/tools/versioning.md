# Version Control

Every committed change to a session (`validate_knowledge`, `evolve_knowledge`,
a merge, a revert, ...) creates a new immutable `Version`. These four tools
let you inspect and travel through that history. All require a `session_id`
obtained from an earlier call.

## `list_versions`

Lists every version recorded for a session, oldest first.

**Parameters:** `session_id` (string, required).

**Response**

```json
{
  "session_id": "sess-abc123",
  "versions": [
    {"version_id": "v-1", "created_at": "2026-07-30T12:00:00", "transaction_id": "tx-1", "metadata": {}},
    {"version_id": "v-2", "created_at": "2026-07-30T12:05:00", "transaction_id": "tx-2", "metadata": {}}
  ]
}
```

## `revert_version`

Reverts a session's current structure to a specific previous version. This
**creates a new version** (a revert is itself a recorded, auditable change —
history is never rewritten or truncated).

**Parameters:** `session_id`, `target_version_id` (both required).

**Response**

```json
{
  "reverted_to": "v-1",
  "new_version_id": "v-3",
  "session_id": "sess-abc123",
  "serialized": "<canonical JSON of the reverted structure>"
}
```

## `compare_versions`

Computes a structural diff between a historical version and the session's
**current** state. Read-only.

**Parameters:** `session_id`, `target_version_id` (both required — the
historical version to compare against; the comparison is always
`target_version_id → current state`).

**Response**

```json
{
  "session_id": "sess-abc123",
  "base_version_id": "v-1",
  "current_version_id": "v-3",
  "direction": "base_to_current",
  "summary": {
    "added_objects": 1, "removed_objects": 0,
    "added_relations": 1, "removed_relations": 0,
    "renamed_objects": 0
  },
  "operations": [
    {"type": "add_object", "identity": {"id": "obj-2", "type": "Lemma", "name": "New"}}
  ]
}
```

`operations` is a serialized list of the same structural-operator shapes
`evolve_knowledge` accepts (`add_object`, `remove_relation`, ...), so it can
be fed back into `evolve_knowledge` on another session if you want to
replay the same change elsewhere.

## `explain_diff`

Same comparison as `compare_versions`, but returns a natural-language
summary plus a richer breakdown — including per-object field-level diffs
and objects that were "re-linked" (a relation whose participant was
replaced elsewhere, so the relation itself is unchanged but now points at
different content).

**Parameters:** `session_id`, `target_version_id` (both required).

**Response**

```json
{
  "session_id": "sess-abc123",
  "base_version_id": "v-1",
  "summary": "Added 1 object(s): New (Lemma). Added 1 relation(s).",
  "details": {
    "added_objects": [{"id": "obj-2", "name": "New", "type": "Lemma", "action": "added"}],
    "removed_objects": [],
    "modified_objects": [],
    "added_relations": [{"id": "rel-2", "action": "added"}],
    "removed_relations": [],
    "modified_relations": [],
    "relinked_relations": [],
    "renamed_objects": []
  }
}
```

Use `compare_versions` when you want a compact, replayable operations list;
use `explain_diff` when a human (or an LLM composing a summary for a human)
needs to understand *what changed and why it matters*.
