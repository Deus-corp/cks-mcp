# Extension Model

`cks-mcp` validates structures against a small, normative core rule set by
default (unique identities, no dangling relations, derivation arity and
acyclicity). Beyond that, six **opt-in extensions** add domain-specific
checks — each one defined in `cks-core` as a `Constraint`, and activated
per call via `validate_knowledge`'s `extensions` parameter:

```json
{"json_data": "...", "extensions": ["embedding_projection", "type_hierarchy"]}
```

All six share one property: **additive by default**. A structure that
doesn't use the relevant Knowledge Object type (`EmbeddingProjection`,
`TypeRule`, `MutualExclusionRule`, ...) is entirely unaffected by the
corresponding extension, whether or not you request it — the check only
ever activates on structures that opt in *structurally*, by containing the
declaration type it looks for.

| Name | Constraint identity | Checks |
|------|---------------------|--------|
| `embedding_projection` | `CKS-EXT-EMBEDDING-PROJECTION` | Every `EmbeddingProjection` object has exactly one `represents` link to a real object, and references its vector externally. |
| `verification_record` | `CKS-EXT-VERIFICATION-RECORD` | Every `VerificationRecord` has the right shape and exactly one `verified_by` link. **Enforced unconditionally** — see below. |
| `type_hierarchy` | `CKS-EXT-TYPE-HIERARCHY-CYCLE` | `TypeDefinition.parent_type` chains don't form a cycle. |
| `relation_type` | `CKS-EXT-RELATION-TYPE` | Relations connect object types allowed by any declared `TypeRule`. |
| `mutual_exclusion` | `CKS-EXT-MUTUAL-EXCLUSION` | No pair of relation types declared mutually exclusive both connect the same source→target pair. |
| `functional_relation` | `CKS-EXT-FUNCTIONAL-RELATION` | No source has more than one target via a relation type declared single-valued. |

## `embedding_projection`

Gives citation/retrieval a mechanical anti-hallucination guarantee: an
`EmbeddingProjection` object represents a vector-space embedding of some
other canonical object, without ever holding the vector itself. This
constraint requires:

1. Exactly one `represents` relation from the projection to a real,
   existing source object.
2. A non-empty `store_ref` field pointing at wherever the actual vector
   lives (an external index) — never an inline `vector`/`embedding` key.

If a generation step cites an `EmbeddingProjection`, this constraint
(together with the always-on dangling-relation check) guarantees that
citation resolves to a real object — never a fabricated one.

## `verification_record`

Checks that every `VerificationRecord` has the right **shape**: required
fields present, and exactly one `verified_by` link to the object it's
about. This is a structural check only — it cannot tell a genuine record
from a well-formed fake, because static validation has no way to know
whether the recorded check actually happened.

That's why `validate_knowledge` enforces this extension **unconditionally**
— it activates the moment a `VerificationRecord` object appears in the
structure, regardless of whether you listed it in `extensions`. On top of
that, `cks-mcp` layers a *second*, independent check that `cks-core` has no
way to perform itself: the record's HMAC signature (see
[Security Model](security.md)). Shape and signature together are what make
"verified" mean verified — this extension alone only proves the record is
well-formed, not that it's genuine.

## `type_hierarchy` and `relation_type`

`ObjectIdentity.type` is an unconstrained string by design — CKS has no
built-in taxonomy. These two extensions let a graph declare its *own*
taxonomy, as ordinary Knowledge Objects, and then check against it:

- **`TypeDefinition`** objects (`{"type_name": "Planet", "parent_type":
  "CelestialBody"}`) declare a subtype relationship. `type_hierarchy` flags
  a cycle in the resulting chain (e.g. Planet is-a Moon is-a Planet).
- **`TypeRule`** objects (`{"relation_type": "orbits",
  "allowed_source_types": ["Planet", "Moon"], "allowed_target_types":
  ["Star", "Planet"]}`) declare which types a relation may connect.
  `relation_type` flags any relation of that type connecting a
  disallowed pair — catching something like "Earth orbits Pasta". If two
  `TypeRule` objects declare the same `relation_type`, the last one
  encountered wins (treated as a modeling error to fix, not something the
  constraint reconciles).

## `mutual_exclusion` and `functional_relation`

These declare **contradiction rules**, also as ordinary Knowledge Objects,
catching relations that are each individually well-typed and yet jointly
nonsensical:

- **`MutualExclusionRule`** (`{"relation_type_a": "supports",
  "relation_type_b": "refutes"}`) — flags a graph asserting both relation
  types between the exact same ordered source→target pair.
- **`FunctionalRelationRule`** (`{"relation_type": "orbits"}`) — declares a
  relation type single-valued; flags a source with more than one target
  through it (e.g. both "Earth orbits Sun" and "Earth orbits Mars").

Multiple rule declarations of either kind accumulate (set union), unlike
`TypeRule`'s last-one-wins behavior — there's no conflicting parameter to
arbitrate between two exclusion or functional rules.

**Two ways to run these same two checks:** pass `mutual_exclusion`/
`functional_relation` to `validate_knowledge`'s `extensions` to get
diagnostics as part of validation (and block the version from committing
if they fail); or call
[`detect_contradictions`](tools/verification.md#detect_contradictions)
directly for a read-only report against the current state without
attempting to validate or commit anything. Same rules, same rule objects —
different tool depending on whether you want validation-time enforcement
or an on-demand check.

## Why unconditional enforcement matters

Every other extension is opt-in *and* harmless if skipped — a structure
that doesn't use `EmbeddingProjection` or `TypeRule` objects is simply
unaffected. `verification_record` is the one exception: an unchecked
`VerificationRecord` looks exactly like a checked one to anyone reading the
result downstream. A caller (or a forgetful/malicious model) omitting it
from `extensions` must not be a way to bypass the check — so `cks-mcp`
activates it the moment the relevant object type appears, independent of
what was requested. See [Security Model](security.md) for the full
provenance story this is one half of.
