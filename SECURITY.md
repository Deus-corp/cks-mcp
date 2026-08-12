# Security Policy

## Supported Versions

`cks-mcp` is production/stable and follows semantic versioning where
practical.

Security fixes are provided for the latest released 1.x version. Given the
project's small surface area and single-maintainer model, older 1.x releases
are not separately patched — users are expected to upgrade to the latest
release.

| Version       | Supported |
| ------------- | --------- |
| 1.x (latest)  | ✅        |
| Earlier 1.x   | ❌        |

---

## Reporting a Vulnerability

If you discover a security vulnerability in `cks-mcp`, please report it
responsibly.

Please avoid creating a public GitHub issue for vulnerabilities that could
affect users before they are investigated. Instead, contact the repository
maintainer directly through GitHub.

When reporting a vulnerability, please include:

- a description of the issue;
- affected version;
- reproduction steps;
- expected behavior;
- actual behavior;
- any proof-of-concept if available.

We will acknowledge your report within 48 hours and aim to release a fix
within one week.

---

## Response Process

The project aims to:

1. acknowledge reports promptly;
2. investigate the reported issue;
3. determine severity and impact;
4. prepare an appropriate fix;
5. publish the fix in a future release;
6. acknowledge the reporter when appropriate.

---

## Scope

`cks-mcp` is the boundary between an LLM client and the rest of the CKS
ecosystem, so its primary security considerations are specific to that
boundary:

- SSRF and DNS-rebinding protection on every outbound HTTP request made on
  behalf of a tool call (`verify_source`, `ingest_document`);
- unconditional provenance verification — a `VerificationRecord`'s HMAC
  signature is checked on every code path that can persist or read one,
  regardless of which extensions were requested;
- persistence and handling of the provenance-signing secret
  (`CKS_MCP_SECRET`);
- input validation at the MCP tool boundary before anything reaches
  `cks-runtime` or `cks-core`;
- the optional HTTP transport (`CKS_MCP_HTTP_PORT`) — when enabled, exposes
  MCP over HTTP with CORS support; intended for local development and
  trusted-network integration with clients like `cks-studio`, not for
  exposure on an untrusted network;
- safe handling of LLM-generated output in `construct_knowledge` (parsed
  and validated before it is ever persisted, never executed).

`cks-mcp` does not execute arbitrary code and does not define knowledge
semantics or manage sessions/transactions itself — those responsibilities
belong to `cks-core` and `cks-runtime` respectively; see their own
`SECURITY.md` for the corresponding scope.

---

## Responsible Disclosure

Please allow reasonable time for investigation and remediation before
publicly disclosing security vulnerabilities. Responsible disclosure helps
protect users while fixes are prepared.

---

## Security Philosophy

`cks-mcp` is intentionally a thin translator between MCP and canonical
operations, which shapes how it approaches security:

- fail closed — a malformed request, an unsigned verification record, or a
  failed dry-run never partially applies; nothing is committed unless it
  fully validates;
- defense in depth at the network boundary — SSRF protection validates and
  pins the resolved IP for the actual request, not just the hostname, and
  re-validates every redirect hop;
- no implicit trust in LLM-generated content — output from
  `construct_knowledge` is parsed and validated exactly like any other
  input, never treated as pre-verified because a model produced it;
- delegate, don't reimplement — semantic validation stays in `cks-core` and
  session/transaction integrity stays in `cks-runtime`; `cks-mcp` never
  reinterprets canonical knowledge on its own.

These principles reduce implementation risk and preserve predictable
behavior, but they do not eliminate the need for ongoing security review.
