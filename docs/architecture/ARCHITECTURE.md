# Architecture

**Status:** Living document — reflects the codebase as of `v1.17.x`.

## 1. Purpose

This document defines the architecture of `cks-mcp`: its role in the CKS
ecosystem, the principles guiding its design, and the components that make
it up. It's written for anyone who wants to understand, extend, or embed
the server — not for API consumers, who want
[Tools Reference](../tools/index.md) instead.

Two topics that used to live here now have dedicated documents, since both
grew past what a single "Architecture" section could hold:
[Security Model](../security.md) and [Extension Model](../extensions.md).
The request lifecycle for a representative tool call is in
[Request Lifecycle](request-lifecycle.md).

## 2. Architectural Role

`cks-mcp` is the **Exposure Layer** of the CKS ecosystem: it translates
external, LLM-friendly requests (MCP tool calls) into internal, canonical
operations managed by `cks-runtime` and validated by `cks-core`.

```
LLMs (Claude Desktop, etc.)
        │
        ▼
cks-mcp        ← Exposure Layer
        │
        ▼
cks-runtime    ← Operational Layer (sessions, transactions, storage, versioning)
        │
        ▼
cks-core       ← Semantic Layer (canonical structure, validation, evolution)
```

`cks-mcp` contains **no semantic logic** and **no operational state
management** of its own. It is a thin, stateless translator between two
protocols — Model Context Protocol and CKS Canonical Operations — plus the
integrity guarantees (provenance, SSRF protection) that only make sense at
the boundary between an untrusted LLM and the rest of the ecosystem.

## 3. Architectural Principles

**Thin translator.** The server's job is mapping MCP tool calls to
`cks-runtime` operations and returning the results — never implementing
validation, evolution, or persistence logic itself. See
[ADR-001](../adr/ADR-001%20Thin%20Translator.md).

**Provenance over trust.** An LLM can generate convincing but fabricated
data. The server never trusts the content of a request for operations like
source verification — it enforces provenance instead: a `VerificationRecord`
is only genuine if `verify_source` built it. See
[Security Model](../security.md).

**Unconditional safety.** Critical integrity checks don't depend on the
LLM asking for them correctly. A forgetful or malicious model might omit
an `extensions` parameter, so checks like `VerificationRecord` signature
verification run regardless. See [Extension Model](../extensions.md#why-unconditional-enforcement-matters).

**Defense in depth.** Security protections are implemented at multiple
independent levels rather than relying on any single check — see
[Security Model](../security.md) for how this plays out in SSRF
protection specifically.

## 4. Components

```
server.py            MCP transport (JSON-RPC over stdio)
  └─ registry.py        Tool schemas + dispatch, wrapped in middleware
       └─ tools/           24 operation handlers, grouped into 21 per-tool packages
middleware.py         Composable validation stacks (require_fields, ...)
errors.py             Structured, LLM-friendly error responses
provenance.py         HMAC signing/verification for VerificationRecord
resources.py          MCP Resources — sessions/versions as browsable URIs
prompts.py            MCP Prompts — templated multi-tool workflows
observability.py      Structured stderr logs + EventBus subscriptions
telemetry.py          In-memory per-tool call metrics (get_metrics)
diffing.py            Shared field-level diff (merge conflicts, explain_diff)
paths.py              Resolves the ~/.cks-mcp data directory
```

### `server.py` — MCP Transport

Owns the JSON-RPC-over-stdio transport, the MCP lifecycle methods
(`initialize`, `ping`, `tools/list`, `resources/list`, `resources/read`,
`prompts/list`, `prompts/get`), and routes `tools/call` to the registry.
Reads a `.env` file at `~/.cks-mcp/.env` on startup if present (see
[Getting Started](../getting-started.md#optional-environment-variables)).

### `registry.py` — Tool Registry & Schemas

The `TOOLS` dict: one entry per tool, assembled from that tool's
`tools/<name>/schema.py` (its `name`, `description`, `inputSchema`) plus its
handler, wired through `middleware.py`'s composition helpers
(`_wrap` / `_wrap_session` / `_wrap_open_session`) rather than each handler
managing its own validation stack.

### `tools/` — Operation Handlers

Each of the 24 tools lives in its own package under `tools/<name>/`
(a small number of packages hold two closely related tools, e.g.
`tools/revert/` has both `list_versions` and `revert_version`) — see
[Tools Reference](../tools/index.md) for the full, grouped list with
parameters and examples. Each package has:
- `handler.py` — the async implementation, a standalone module
  implementing a single canonical operation.
- `schema.py` — a plain Python dict with the tool's MCP schema, kept
  separate from the implementation so it can be reviewed/edited on its
  own; shared description text lives in `tools/_shared.py`.
- `__init__.py` — re-exports the handler function(s) as the package's
  public API.

### `middleware.py` — Composable Middleware

A small decorator-factory layer (`require_fields`, `require_session`,
`require_open_session`, `catch_unhandled_errors`, composed via
`with_middleware`) sitting between the transport and each handler. See
[ADR-003](../adr/ADR-003%20Middleware%20Stack.md) for why this replaced
per-handler validation.

### `errors.py` — Structured Errors

Maps internal failures to structured `{"error": ..., "message": ...}`
dicts that give the calling LLM actionable information, instead of a raw
exception or protocol-level fault.

### `provenance.py` — Cryptographic Trust

Signs and verifies `VerificationRecord` objects. See
[Security Model](../security.md#provenance-enforcement) for the full
mechanism, and [ADR-002](../adr/ADR-002%20Provenance%20Signing.md) for why
HMAC over a process-local secret rather than an alternative like
asymmetric signing.

### `resources.py` / `prompts.py` — MCP-Native Extras

Expose sessions/versions as browsable Resources and common multi-tool
workflows as templated Prompts. See [Resources](../protocol/resources.md)
and [Prompts](../protocol/prompts.md) — these are documented nowhere else,
so read those directly rather than expecting more detail here.

### `observability.py` / `telemetry.py` — Observability

`observability.py` writes structured JSON logs to stderr (never stdout,
which the MCP transport owns) and subscribes to `cks-runtime`'s EventBus
for lifecycle events. `telemetry.py` is a separate in-memory aggregator —
deliberately split out so the "log to stderr" concern and the "aggregate
for `get_metrics`" concern can change independently.

### `diffing.py` — Shared Diff Helper

One `field_level_diff` implementation shared by `merge.py`'s conflict
reporting and `explain_diff.py`, so "what changed about this identity"
is computed the same way in both places instead of two implementations
slowly drifting apart.

### `paths.py` — Data Directory

Resolves `~/.cks-mcp` (or `CKS_MCP_DATA_DIR`) once, cwd-independent — the
one place the SQLite database, the persisted provenance secret, and the
optional `.env` file all live.

## 5. Where to go next

- [Request Lifecycle](request-lifecycle.md) — how a `validate_knowledge`
  call actually flows through these components.
- [Security Model](../security.md) — the full SSRF and provenance story.
- [Extension Model](../extensions.md) — the six opt-in validation
  extensions.
- [ADRs](../adr/) — why specific components look the way they do.
