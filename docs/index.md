# cks-mcp

> Model Context Protocol server for Canonical Knowledge Structure.

`cks-mcp` gives LLMs a **canonical knowledge backbone**: a persistent,
versioned, verifiable place to put structured knowledge, instead of holding
it — and quietly forgetting or hallucinating it — in a context window.

It exposes **63 tools** over MCP, backed by the deterministic, immutable
semantics of [`cks-core`](https://github.com/PunctumActus/cks-core) and the
async operational management of
[`cks-runtime`](https://github.com/PunctumActus/cks-runtime). Every tool call
that mutates state runs inside a Runtime **Session** and **Transaction**,
producing an immutable **Version** — so every change is reproducible and
auditable after the fact.

## Why cks-mcp?

LLMs generate plausible but unverified statements. `cks-mcp` gives them a
place to put knowledge that must be explicit, checkable, and traceable to
its origin:

- **Citations can't be fabricated silently** — the `embedding_projection`
  extension mechanically flags a reference to a source that doesn't exist.
- **"Verified" has to mean verified** — `verify_source` performs a real
  HTTP check and cryptographically signs the result; every other tool
  rejects a `VerificationRecord` without a valid signature, even if the
  model never asked for the check.
- **Nothing is silently lost** — every committed change is a new immutable
  version; `list_versions`, `compare_versions`, `explain_diff`, and
  `revert_version` give full time-travel over a session's history.
- **Contradictions are caught, not repeated** — `detect_contradictions`
  flags mutual exclusions and functional-relation violations mechanically.
- **Hypotheses are cheap** — `fork_sandbox` lets an LLM try a risky edit in
  complete isolation and see the diff, with zero risk to the real session.

## Role in the CKS ecosystem

```
LLMs (Claude Desktop, etc.)
        │
        ▼
cks-mcp        ← Exposure Layer: thin, stateless MCP ⇄ canonical-operation translator
        │
        ▼
cks-runtime    ← Operational Layer: sessions, transactions, storage, versioning
        │
        ▼
cks-core       ← Semantic Layer: canonical structure, validation, evolution
```

`cks-mcp` contains **no semantic logic** of its own — validation and
evolution rules live in `cks-core`; session/transaction/storage management
lives in `cks-runtime`. Its job is translating MCP tool calls into
canonical operations and enforcing the integrity guarantees (provenance,
SSRF protection) that only make sense at the boundary between an LLM and
the rest of the ecosystem. See [Architecture](architecture/ARCHITECTURE.md)
for the full picture.

## Documentation

| Page | Covers |
|------|--------|
| [Getting Started](getting-started.md) | Install, connect to Claude Desktop, first session |
| [Tools Reference](tools/index.md) | All 63 tools, grouped by function, with request/response examples |
| [Architecture](architecture/ARCHITECTURE.md) | Layering, components, and the [request lifecycle](architecture/request-lifecycle.md) |
| [Security Model](security.md) | SSRF protection, provenance signing, defense in depth |
| [Extension Model](extensions.md) | The opt-in `extensions` parameter and what each of the eleven checks |
| [MCP Resources](protocol/resources.md) & [Prompts](protocol/prompts.md) | The two MCP-native features the server exposes beyond its 63 tools |
| [ADRs](adr/) | Why specific architectural decisions were made — thin translator, provenance signing, middleware, extension model |

## Learning Path

1. Read [Getting Started](getting-started.md) and connect the server to
   Claude Desktop (or any MCP client).
2. Skim the [Tools Reference](tools/index.md) overview table to see what's
   available, then read the group relevant to what you're building.
3. If you're extending or embedding the server rather than just using it,
   read [Architecture](architecture/ARCHITECTURE.md) and its
   [Request Lifecycle](architecture/request-lifecycle.md) for the
   component layout, [Security Model](security.md) and
   [Extension Model](extensions.md) for the guarantees it enforces, and
   the [ADRs](adr/) for why specific decisions were made.

## Current Status

The project is production/stable (`v1.58.0` — see
[CHANGELOG](../CHANGELOG.md) for the exact history and
[ROADMAP](../ROADMAP.md) for what's next). It ships with a persistent
SQLite/PostgreSQL-backed runtime, real HuggingFace-embedding semantic
search, an LLM abstraction layer (Ollama/Anthropic/OpenAI-compatible), five
autonomous agents (Critic, Enrichment, Fork Resolution, Pipeline, plus
in-process sweepers), and a test suite (879 tests: 873 passing, 6 skipped)
covering core functionality, security, and integrations.

## License

MIT — see [LICENSE](../LICENSE).
