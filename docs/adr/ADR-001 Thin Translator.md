# ADR-001

# Thin Translator

**Status:** Accepted

**Date:** 2026-07-30

**Category:** Architecture Decision Record

---

# Context

`cks-mcp` sits directly below the LLM client in the CKS ecosystem's
layering — see [Architecture § Architectural Role](../architecture/ARCHITECTURE.md#2-architectural-role).
`cks-runtime` documents this same kind of layering discipline one level
in, between itself and `cks-core`, in its own ADR-001 ("Runtime
Layering"). This decision extends that same discipline one layer further
out, to the MCP boundary.
Every canonical operation a tool call performs — validating a structure,
evolving it, merging two branches — already has a home: `cks-core` owns
semantic behavior, `cks-runtime` owns sessions, transactions, and storage.

# Problem

An MCP server is the natural place to add conveniences: caching, request
batching, alternate validation shortcuts, session bookkeeping outside the
Runtime's own model. Each of these would be a small, locally-reasonable
addition. Accumulated, they would duplicate — and eventually drift from —
logic that `cks-core` and `cks-runtime` already own, exactly the coupling
Runtime Layering exists to prevent one layer further in.

# Decision

`cks-mcp` implements **no semantic logic and no operational state
management of its own**. Its only responsibility is translating MCP tool
calls into `cks-runtime` operations and translating the results back into
MCP-shaped responses.

Concretely:

- Every tool handler in `tools/` either calls into `cks-runtime` (session,
  transaction, operation) or `cks-core` (parsing, serialization) to do the
  actual work — it does not reimplement validation or evolution rules.
- Concerns that *are* legitimately the server's own — MCP transport,
  provenance signing, SSRF protection, structured error shaping — live in
  dedicated modules (`server.py`, `provenance.py`, `verify_source.py`,
  `errors.py`) rather than inside tool handlers, and are documented as
  the server's actual responsibilities in
  [Architecture](../architecture/ARCHITECTURE.md#4-components).

# Consequences

Positive:

- `cks-mcp` can add new tools without ever risking semantic drift from
  `cks-core` — a new tool is a new translation, not a new rule.
- Bugs in validation or evolution semantics are fixed once, in `cks-core`
  or `cks-runtime`, and every consumer (not just `cks-mcp`) benefits.
- The server stays swappable: another MCP-like adapter could expose the
  same `cks-runtime` operations differently without `cks-core` or
  `cks-runtime` needing to change.

Negative:

- Some conveniences that would be trivial to bolt on locally (e.g. a
  cache of recently-validated structures) require a justified exception
  or an upstream change instead of a quick local patch.
- Provenance and SSRF protection, while consistent with "own only what's
  genuinely yours," still make `cks-mcp` larger than a pure pass-through
  would be — see [ADR-002](ADR-002%20Provenance%20Signing.md) for why that
  specific exception is justified.

# Alternatives Considered

## Embed a local validation fast-path

Skip a full `cks-core` validation round-trip for common cases by
reimplementing a subset of the rules directly in `cks-mcp`. Rejected: any
divergence between the fast-path and `cks-core`'s actual rules becomes a
silent correctness bug, and `cks-core`'s own evolution would require this
duplicate to be kept in sync by hand.

## Session bookkeeping in `cks-mcp`

Track session state directly in the MCP server process instead of
delegating entirely to `cks-runtime.Runtime`. Rejected: this is exactly
the "Runtime-Embedded Semantics" pattern the ecosystem's Runtime Layering
ADR rejects one layer down, applied to `cks-mcp` instead of an adapter —
the reasoning transfers unchanged.

# Rationale

Keeping `cks-mcp` thin means every consumer of `cks-core`/`cks-runtime` —
not just the MCP surface — benefits from correctness fixes and semantic
evolution in one place. The cost (occasionally needing an upstream change
instead of a local shortcut) is small compared to the alternative: a
translator that quietly becomes a second, divergent implementation of
rules that already exist.

# Status

Accepted. New tools and features should extend `cks-runtime`/`cks-core`
when they need new *semantic* capability, and add to `cks-mcp` only the
translation and MCP-boundary concerns.
