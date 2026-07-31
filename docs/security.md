# Security Model

`cks-mcp` sits at the boundary between an LLM and the rest of the CKS
ecosystem. Its trust model follows from one premise: **the LLM and its
input are untrusted**. The server enforces every safety and integrity rule
itself, regardless of whether the LLM correctly requests it, remembers to
ask, or is actively trying to produce convincing-looking fabricated data.

This covers two independent concerns: preventing the server from being
used as an SSRF vector, and preventing fabricated verification claims from
ever being treated as genuine.

## SSRF & DNS-Rebinding Protection

`verify_source` and `ingest_document` are the only two tools that make an
outbound HTTP request on the server's behalf, and both route through the
same `_safe_request` implementation — the protection isn't duplicated
per-tool, and a new tool that needs to fetch a URL gets the same guarantees
by construction.

The request goes through three checks, in order:

1. **Scheme allow-list.** Only `http` and `https` are accepted.
2. **Public-IP validation.** The hostname is resolved, and *every* IP it
   resolves to must be a public address — private, loopback, link-local,
   multicast, reserved, and unspecified ranges are all blocked. Two ranges
   Python's `ipaddress` module doesn't classify as private but that aren't
   public internet either are also explicitly blocked: `100.64.0.0/10`
   (RFC 6598 Shared Address Space — the range Tailscale and several cloud
   providers use for internal node addressing) and `192.0.0.0/24` (IETF
   protocol assignments). If a hostname resolves to *any* non-public
   address alongside public ones, the whole request is refused — not just
   the unsafe address.
3. **DNS-pinned connection.** The actual request is pinned to the specific
   IP validated in step 2, via a reference-counted, thread-local override
   of `socket.getaddrinfo`. This closes the gap between "the address we
   checked" and "the address we connect to" — without it, a DNS response
   could legitimately differ between the validation lookup and the
   request itself (classic DNS rebinding). The override preserves SNI and
   TLS certificate validation, unlike mutating the connection pool
   directly.

**Redirects are followed manually, one hop at a time**, up to a fixed
limit — never via `requests`' built-in `allow_redirects=True`. Every new
`Location` is re-resolved and re-validated through the same three checks
before it's followed. Without this, a server that passed the initial
check could redirect straight past it to an internal or cloud-metadata
endpoint.

## Provenance Enforcement

A `VerificationRecord` is supposed to mean "this claim was actually
checked." The problem: a `VerificationRecord` that was *never* checked —
just hand-crafted by an LLM to look convincing — is structurally
indistinguishable from a genuine one. Static validation alone cannot tell
them apart (see [`verification_record`](extensions.md#verification_record)
for why that's a hard limit, not an oversight). Closing that gap needs two
things working together:

1. **A single sanctioned constructor.** `verify_source` is the *only* tool
   that builds a `VerificationRecord` — always from the result of a real
   HTTP request it just performed itself, never from caller-supplied
   fields.
2. **A signature only that constructor can produce.** Every record
   `verify_source` builds is signed with an HMAC-SHA256 over its content
   (`record_id`, `subject_id`, `checked_at`, `checked_via`, `http_status`),
   keyed by a secret held only by the running server process
   (`CKS_MCP_SECRET`, persisted to `~/.cks-mcp/.cks_provenance_secret` on
   first use so a restart doesn't invalidate history).

Everywhere else a structure can enter or leave the system —
`validate_knowledge`, `evolve_knowledge`, `merge_knowledge`,
`merge_branch`, and the `json_data` fallback paths of
`serialize_knowledge`/`explain_knowledge`/`detect_contradictions` — checks
every `VerificationRecord` in it against that signature, **unconditionally**,
whether or not the caller asked for the `verification_record` extension.
A record without a valid signature produces a `CKS-MCP-UNVERIFIED-PROVENANCE`
diagnostic and is treated as unverified.

Two extra edge cases the check closes:

- **Structural identification, not label-based.** A relation is recognized
  by having `participants` + `relation_type` in its structure — the same
  way `cks-core` itself identifies one — never by trusting
  `identity.type == "Relation"`. A forged record linked via a `verified_by`
  relation carrying some other `identity.type` would otherwise slip past
  as "unlinked" (a warning) instead of hitting the signature check (an
  error).
- **Ambiguous references are rejected outright.** If more than one subject
  claims the same `VerificationRecord` via `verified_by`, that's flagged
  as `CKS-MCP-AMBIGUOUS-VERIFICATION-REFERENCE` before the signature is
  even checked — an ambiguous claim isn't something a signature check can
  resolve.

**Nothing invalid is ever committed, even partially.** For a fresh
`json_data` structure with a forged record, `validate_knowledge` doesn't
even register the session via `runtime.create_session()` — it dry-runs
against a throwaway, unregistered `RuntimeSession` first. If it registered
the session before the provenance check, the forged record would already
be live and readable through `serialize_knowledge`, `query_subgraph`, or an
MCP Resource on that `session_id`, regardless of what the validation
response itself said. The same dry-run-before-commit shape is used by
`evolve_knowledge`, `merge_branch`, and `merge_knowledge` for the same
reason: a version is exactly what every downstream reader will treat as
trustworthy, so nothing becomes a version unless it's already known-good.

## Trust Boundary Summary

| Layer | Responsibility |
|-------|-----------------|
| `cks-mcp` | Enforces provenance and SSRF protection at the MCP boundary — the only layer that knows an `VerificationRecord` needs a signature, or that a URL came from an untrusted LLM. |
| `cks-runtime` | Session/transaction integrity, storage safety — doesn't know or care what a `VerificationRecord` is. |
| `cks-core` | Structural and semantic validation — checks a `VerificationRecord`'s *shape*, never its provenance (it never sees the signing key). |

See [`SECURITY.md`](../SECURITY.md) for how to report a vulnerability, and
[Extension Model](extensions.md) for the full opt-in constraint set this
document's provenance section is one (unconditionally-enforced) part of.
