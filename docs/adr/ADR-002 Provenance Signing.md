# ADR-002

# Provenance via HMAC Signing

**Status:** Accepted

**Date:** 2026-07-30

**Category:** Architecture Decision Record

---

# Context

`cks-core`'s `verification.py` establishes that a `VerificationRecord`'s
*shape* can be validated structurally, but its *provenance* — whether the
recorded check actually happened — cannot be verified by `cks-core` at
all: static validation has no way to distinguish a genuine record from a
well-formed fabrication, and execution environments are explicitly out of
scope for the Core Specification (CKS-001 Non-Goals). `cks-core`'s own
docstring for this constraint states the fix belongs "one layer up": a
dedicated runtime/MCP tool should be the sole sanctioned constructor of
`VerificationRecord` objects.

# Problem

`cks-mcp` needed a way to guarantee, mechanically, that a
`VerificationRecord` present in a structure was actually produced by a
real HTTP check (`verify_source`) — not authored directly by an LLM trying
to look convincing — without requiring the caller to opt in correctly
every time.

# Decision

- `verify_source` is the **sole sanctioned constructor** of
  `VerificationRecord` objects: it performs the real HTTP check itself and
  builds every field of the record from the actual result, never from
  caller-supplied values.
- Every record it builds is signed with **HMAC-SHA256** over its content
  (`record_id`, `subject_id`, `checked_at`, `checked_via`, `http_status`),
  keyed by a secret (`CKS_MCP_SECRET`) held only by the server process.
- The secret is **persisted to disk** on first use (`~/.cks-mcp/.cks_provenance_secret`)
  rather than regenerated per process start, so a server restart doesn't
  invalidate every previously signed record.
- Verification of this signature is performed **unconditionally** on every
  `VerificationRecord` encountered by `validate_knowledge` and every other
  entry/exit point for a structure — not gated behind the
  `verification_record` extension — because an unchecked record is
  indistinguishable from a checked one to anyone reading the result later.

# Consequences

Positive:

- A forged `VerificationRecord` can never be indistinguishable from a
  genuine one downstream — the signature check is a hard gate, not an
  opt-in.
- The secret never needs to be shared outside the process (no distributed
  key management), which keeps the implementation simple for a
  single-server deployment.
- Persisting the secret means history remains verifiable across restarts,
  which a per-process-random secret would silently break.

Negative:

- **Single-server trust boundary.** The signature only proves "this
  server's `verify_source` produced this record" — it says nothing across
  multiple `cks-mcp` instances unless they share `CKS_MCP_SECRET`
  explicitly. This is an accepted limitation for the current single-server
  deployment model; a multi-instance or federated deployment (see
  `ROADMAP.md`'s "Distributed Knowledge Graphs") will need to revisit this.
- Losing the secret file invalidates every previously signed record's
  verifiability. There is currently no rotation or multi-key verification
  scheme.

# Alternatives Considered

## Asymmetric signing (public/private keypair)

Would let a third party verify a record's provenance without holding a
shared secret. Rejected for now: the only verifier that currently exists
*is* the same server process that created the record, so asymmetric
signing adds key-management complexity (rotation, distribution) with no
present benefit. Worth revisiting if/when a federated deployment needs
cross-server verification.

## Trust the LLM's self-report, with a confidence heuristic

E.g., flag records that "look" fabricated via pattern heuristics on
`checked_via` or timestamps. Rejected outright: this is exactly the kind
of thing `cks-core`'s own docstring warns cannot be solved statically — a
sufficiently careful fabrication passes any heuristic that isn't
cryptographic provenance.

## Gate the signature check behind the `verification_record` extension

Consistent with how the other five extensions work. Rejected: unlike
those five, an unchecked `VerificationRecord` is not "harmlessly ignored"
— it's indistinguishable from a checked one, so making the check optional
would make forgery trivial for any caller that simply omits the
extension. See [Extension Model § Why unconditional enforcement matters](../extensions.md#why-unconditional-enforcement-matters).

# Rationale

Provenance-over-trust only works if it can't be bypassed by omission. HMAC
signing with a sole sanctioned constructor gives a cheap, mechanically
enforceable guarantee for the deployment model `cks-mcp` actually has
today (a single server process), while keeping the door open to a
stronger scheme later without changing the record shape itself.

# Status

Accepted. Revisit the single-secret model specifically if/when multi-
instance or federated deployment becomes a real requirement.
