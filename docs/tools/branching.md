# Branching & Merging

Tools for isolating an experiment from a session's main line, and later
reconciling it — either by promoting it back in, or discarding it.

## `create_branch`

Forks a new session from an existing one, either from its current state or
from a specific historical version.

**Parameters:** `session_id` (required, parent), `version_id` (optional —
fork from this historical version instead of current state).

> **Tip:** pass `version_id` when you intend to `merge_branch` the result
> back later. It records the exact fork point as the branch's
> `parent_version_id`, which `merge_branch` uses automatically as its merge
> base. Without it, `merge_branch` needs an explicit `base_version_id`.

**Response**

```json
{
  "session_id": "sess-branch-1",
  "parent_session_id": "sess-abc123",
  "parent_version_id": "v-2",
  "message": "Branch session sess-branch-1 created from parent sess-abc123."
}
```

## `merge_branch`

Session-aware three-way merge: merges a branch's changes into a target
session. Unlike `merge_knowledge`, the merge base is resolved **automatically**
from the branch's recorded fork point — you never supply it yourself
(unless the branch wasn't created via `create_branch`'s `version_id`, in
which case pass `base_version_id`).

**Parameters**

| Name | Required | Description |
|------|----------|--------------|
| `target_session_id` | yes | Session to merge into. |
| `source_session_id` | yes | Branch session being merged in. |
| `base_version_id` | no | Override the automatic merge base. |
| `resolutions` | no | Per-object conflict resolutions (see below). |

**On success**, commits the merge as a new version of the target:

```json
{"merged": true, "serialized": "<canonical JSON>", "session_id": "sess-abc123", "version_id": "v-4"}
```

**On conflict**, nothing is committed — you get a structured report instead:

```json
{
  "merged": false,
  "message": "Merge conflict detected. For each entry in 'conflicts' below, ...",
  "conflicts": [
    {"object_id": "obj-1", "target_diff": {...}, "source_diff": {...}}
  ]
}
```

Do **not** retry `merge_branch` unchanged after a conflict. Either:

1. Retry with a `resolutions` argument, keyed by `object_id`, valued
   `"branch_a"` (keep target's version), `"branch_b"` (keep source's
   version), `null` (drop the object), or a full object definition to
   synthesize a new value. You can resolve only some conflicts per call —
   everything else merges normally, and unresolved ids are reported again.
2. Or apply your resolution directly to the target session with
   `evolve_knowledge`, then retry `merge_branch` with no `resolutions`.

Either way, `close_session` the source branch once it's fully integrated.
Many disjoint-field conflicts (edits to *different* fields of the same
object) are resolved automatically without ever reaching you — see
ADR-007 in `cks-runtime`. If that fast path is unavailable in your storage
backend, the response includes a `field_level_auto_merge_note` explaining why.

## `merge_knowledge`

The base primitive `merge_branch` is built on: a three-way merge of three
**raw** structures — you supply the common ancestor yourself instead of it
being resolved from a session's history. Use this when you're not working
with live sessions (e.g. merging two externally-produced structures).

**Parameters:** `json_data_base`, `json_data_branch_a`, `json_data_branch_b`
(all required), `resolutions` (optional, same shape as `merge_branch`).

**Response shape** mirrors `merge_branch`: `{"merged": true, "serialized": ...}`
on success, `{"merged": false, "conflicts": [...]}` on conflict. A
`dropped_relations` field appears when a relation was dropped because one
of its participants didn't survive the merge.

## `fork_sandbox`

The "what-if" tool: forks an isolated branch, optionally applies a
hypothesis (an `operations` list) to it immediately, and reports the diff
from the fork point — all without ever touching the parent session. Safe to
throw away.

**Parameters**

| Name | Required | Description |
|------|----------|--------------|
| `session_id` | yes | Parent session to fork from. |
| `version_id` | no | Fork from this historical version instead of current state. |
| `hypothesis` | no | Short description, echoed back for logging. |
| `operations` | no | Evolution operations to apply immediately in the sandbox. |

**Response**

```json
{
  "sandbox_session_id": "sess-sandbox-1",
  "parent_session_id": "sess-abc123",
  "fork_version_id": "v-2",
  "operations_applied": 1,
  "diff_from_fork_point": {
    "summary": {"added_objects": 1, "removed_objects": 0, "added_relations": 0, "removed_relations": 0, "renamed_objects": 0},
    "operations": [{"type": "add_object", "identity": {...}}]
  },
  "hypothesis": "what if we add a counter-example object",
  "message": "Sandbox session 'sess-sandbox-1' is an isolated fork of 'sess-abc123'; ..."
}
```

If `operations` fails validation or provenance, the sandbox is closed
automatically and an `error` is returned — nothing is left dangling. Keep
exploring the sandbox with `evolve_knowledge`, promote it with
`merge_branch` once you're satisfied, or discard it with `close_session` —
there's no obligation to merge.

## `close_session`

Releases a session from the runtime. Typical use: after `merge_branch`
reports success, close the source branch that was just merged in.

**Parameters:** `session_id` (required).

**Response:** `{"session_id": "...", "closed": true}`.
