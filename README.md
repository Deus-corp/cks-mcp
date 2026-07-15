# CKS MCP Server

> Model Context Protocol server for Canonical Knowledge Structure.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-20%20passing-brightgreen)

`cks-mcp` is an MCP (Model Context Protocol) server that provides LLMs
with structured, verifiable knowledge operations through the CKS
ecosystem.  It exposes six tools—validate, query, compare, evolve,
derive, and construct—each backed by the deterministic, immutable
semantics of `cks-core`.

---

# Why cks-mcp?

LLMs generate plausible but unverified statements.  `cks-mcp` gives them
a **canonical knowledge backbone**: every piece of information must be
explicitly structured, validated against formal constraints, and
traceable to its origin.  This minimises hallucinations and makes AI‑
generated knowledge auditable.

---

# Installation

```bash
pip install cks-mcp
```

The server requires `cks-core` (installed automatically as a dependency).

---

# Quick Start

Launch the server:

```bash
cks-mcp
```

An MCP client (Claude Desktop, any MCP-compatible LLM) can then connect
and call tools.

---

# Available Tools

| Tool | Description |
|------|-------------|
| `validate_knowledge` | Validate a Knowledge Structure and return diagnostics. |
| `query_relations`   | Find all relations for a given entity. |
| `compare_structures`| Check semantic equivalence of two structures. |
| `evolve_knowledge`  | Apply Genesis/Decay operators to evolve a structure. |
| `derive_knowledge`  | Derive a new Knowledge Object from existing premises. |
| `construct_knowledge`| Parse and construct a Knowledge Structure (coming soon). |

---

# Usage Example

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "validate_knowledge",
    "arguments": {
      "json_data": "{\"objects\":[{\"identity\":{\"id\":\"obj-1\",\"type\":\"Definition\",\"name\":\"Test\"},\"structure\":{}}]}"
    }
  }
}
```

Response:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": "{\"valid\": true, \"error_count\": 0, \"warning_count\": 0, \"diagnostics\": []}"
}
```

---

# Testing

```bash
python -m pytest -v
```

20 tests, all passing.

---

# Ecosystem

- **cks-core** — the canonical knowledge engine ([repo](https://github.com/Deus-corp/CKS))
- **CKS Specifications** — formal theory behind the system ([DOI](https://zenodo.org/records/21332624))

---

# License

MIT
