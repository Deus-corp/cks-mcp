# ADR-004

# Opt-in Extension Model

**Status:** Accepted

**Date:** 2026-07-30

**Category:** Architecture Decision Record

---

# Context

`cks-core` defines a small, normative core rule set (`BUILTIN_CONSTRAINTS`)
that applies to every structure unconditionally, plus a growing set of
domain-specific `OPTIONAL_CONSTRAINTS` — citation integrity, declared type
ontologies, contradiction rules — that are useful but not universal: a
structure that doesn't declare a type hierarchy shouldn't pay any cost, or
receive any diagnostics, for a constraint checking type-hierarchy cycles.

# Problem

`cks-mcp` needed a way for an MCP tool caller to select which of these
optional constraints apply to a given `validate_knowledge` call, without:

- hard-coding a fixed subset into the server (new `cks-core` extensions
  should become available without a `cks-mcp` code change beyond a version
  bump), or
- silently applying every optional constraint to every call regardless of
  relevance, which would produce diagnostic noise for structures that
  don't use the relevant Knowledge Object types at all.

# Decision

`cks-core`'s `builtin.py` defines a stable-name → `Constraint` mapping
(`OPTIONAL_CONSTRAINTS_BY_NAME`) specifically for API boundaries like this
one. `cks-mcp`'s `validate_knowledge` accepts an `extensions: list[str]`
parameter of these stable names (`"embedding_projection"`,
`"type_hierarchy"`, ...), resolves them via this shared registry, and
rejects unknown names with a structured `unknown_extension` error listing
what's actually available.

One exception: `verification_record` is **force-added** whenever a
`VerificationRecord` object is present in the structure, regardless of
whether the caller listed it — see
[ADR-002](ADR-002%20Provenance%20Signing.md) and
[Extension Model § Why unconditional enforcement matters](../extensions.md#why-unconditional-enforcement-matters)
for why this one specific extension isn't allowed to be skippable.

# Consequences

Positive:

- New `cks-core` optional constraints become available to `cks-mcp` by
  bumping the `cks-core` dependency version — no `cks-mcp` code change is
  needed to expose a new stable name, since `EXTENSION_ALIASES` maps
  directly onto `OPTIONAL_CONSTRAINTS_BY_NAME`'s keys.
- Structures that don't use a given extension's object types are
  unaffected whether or not that extension is requested — no diagnostic
  noise, no validation cost paid for irrelevant checks.
- The name → constraint mapping is owned once, in `cks-core`, instead of
  `cks-mcp` maintaining its own parallel table that could drift from what
  `cks-core` actually implements.

Negative:

- A caller (human or LLM) has to know which extension name unlocks which
  check — there's no automatic "detect what this structure needs and
  apply it" behavior. `unknown_extension`'s error message mitigates this
  by listing every available name.
- The one unconditional exception (`verification_record`) makes the model
  slightly less uniform than "everything is opt-in" — a deliberate
  trade-off, not an oversight (see Alternatives below).

# Alternatives Considered

## Apply every optional constraint to every call

Simplest possible model — no `extensions` parameter at all. Rejected:
this would mean, e.g., every structure with a `TypeRule` object anywhere
gets `relation_type` checking whether or not the caller wants it, and
provides no way to introduce a new optional constraint in `cks-core`
without every existing caller of `cks-mcp` suddenly receiving new
diagnostics on their next call.

## Make `verification_record` opt-in like the other five, for consistency

Rejected — covered in detail in [ADR-002](ADR-002%20Provenance%20Signing.md):
an unchecked `VerificationRecord` is indistinguishable from a checked one
downstream, so making the check skippable would make forgery trivial for
any caller (or model) that simply omits the extension name.

## `cks-mcp`-local extension registry, independent of `cks-core`'s

Rejected: this is the same duplication risk [ADR-001](ADR-001%20Thin%20Translator.md)
argues against generally — a second table mapping names to constraints
would need to be kept in sync by hand with `cks-core`'s own
`OPTIONAL_CONSTRAINTS_BY_NAME` every time an extension is added or
changed.

# Rationale

Owning the name → constraint mapping in `cks-core` and treating `cks-mcp`
as a thin resolver over it keeps the extension surface consistent with
[ADR-001](ADR-001%20Thin%20Translator.md)'s thin-translator principle,
while still giving callers fine-grained, additive-by-default control over
which optional checks apply to a given call.

# Status

Accepted. The one unconditional exception (`verification_record`) is
intentional and should not be relaxed to "opt-in for consistency" without
revisiting [ADR-002](ADR-002%20Provenance%20Signing.md)'s reasoning first.
