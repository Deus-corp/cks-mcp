# CKS MCP Server

> Model Context Protocol server for Canonical Knowledge Structure.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-19%20passing-brightgreen)

`cks-mcp` is an MCP (Model Context Protocol) server that provides LLMs
with structured, verifiable knowledge operations through the CKS
ecosystem.  It exposes four tools—`validate_knowledge`, `serialize_knowledge`,
`explain_knowledge`, and `evolve_knowledge`—each backed by the deterministic,
immutable semantics of `cks-core` and the operational management of `cks-runtime`.

Every tool call now creates a **Runtime Session** and **Transaction**,
producing an immutable **Version** and collecting **Diagnostics**.
This guarantees full auditability and reproducibility.

---

# Ecosystem

CKS Core is the semantic foundation of the CKS ecosystem.
Other projects build upon it:

| Project | Description | Repository |
|---------|-------------|------------|
| **cks-core** | Canonical semantic engine | [Deus-corp/cks-core](https://github.com/Deus-corp/cks-core) |
| **cks-runtime** | Operational environment – sessions, transactions, persistence | [Deus-corp/cks-runtime](https://github.com/Deus-corp/cks-runtime) |
| **cks-mcp** | MCP server – exposes CKS to LLMs (this repository) | [Deus-corp/cks-mcp](https://github.com/Deus-corp/cks-mcp) |

---

# Why cks-mcp?

LLMs generate plausible but unverified statements.  `cks-mcp` gives them
a **canonical knowledge backbone**: every piece of information must be
explicitly structured, validated against formal constraints, and
traceable to its origin.  This minimises hallucinations and makes AI‑
generated knowledge auditable.

In addition to the built‑in validation rules, `validate_knowledge`
supports **opt‑in extensions** — extra, non‑default constraints that
can be activated per call without affecting global state. The first
available extension, `embedding_projection`, mechanically detects
**citation hallucinations**: it verifies that every `EmbeddingProjection`
points to a real source object that actually exists in the structure.
This turns the abstract goal of "reducing hallucinations" into a
concrete, machine‑checkable property of the knowledge graph.

---

# Installation

```bash
pip install cks-mcp
```

The server requires `cks-runtime` (which includes `cks-core`) as a dependency.

---

# Quick Start

## Launch the MCP server

```bash
cks-mcp
```

An MCP client (Claude Desktop, any MCP-compatible LLM) can then connect
and call tools.

## Connect to Claude Desktop

1. Install all three packages into a single virtual environment:
   ```bash
   python3 -m venv cks-env
   source cks-env/bin/activate
   pip install cks-core cks-runtime cks-mcp
   ```

2. Open Claude Desktop, go to **Settings → Developer → Edit Config**.
   The configuration file (`claude_desktop_config.json`) will open.
   Add the following block (adjust the path to your `cks-mcp` executable):
   ```json
   {
     "mcpServers": {
       "cks-mcp": {
         "command": "/absolute/path/to/cks-env/bin/cks-mcp"
       }
     }
   }
   ```

3. Save the file and fully restart Claude Desktop (Cmd+Q, then reopen).
   After restart, a connector icon will appear – `cks-mcp` with four tools
   is ready to use.

## Interactive LLM client (Groq / DeepSeek / local)

```bash
export GROQ_API_KEY=your_key_here
python llm_client/cks_llm_client.py --provider groq
```

You can then type natural language requests; the LLM will automatically
call the appropriate CKS tool.

---

# Available Tools

| Tool | Description |
|------|-------------|
| `validate_knowledge` | Validate a Knowledge Structure and return diagnostics. Supports opt‑in extensions (e.g. `embedding_projection`). |
| `serialize_knowledge` | Serialize a Knowledge Structure into canonical JSON. |
| `explain_knowledge` | Produce a semantic explanation of a Knowledge Structure. |
| `evolve_knowledge` | Apply Genesis/Decay operators to evolve a structure. |

---

# Usage Example

```json
{
  "method": "tools/call",
  "params": {
    "name": "validate_knowledge",
    "arguments": {
      "json_data": "{\"objects\":[{\"identity\":{\"id\":\"obj-1\",\"type\":\"Definition\",\"name\":\"Test\"},\"structure\":{}}]}"
    }
  }
}
```

Response (with version and session information):

```json
{
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"valid\": true, \"version_id\": \"...\", \"session_id\": \"...\", \"diagnostics\": [], ...}"
      }
    ]
  }
}
```

## Catching citation hallucinations

Pass `"extensions": ["embedding_projection"]` to `validate_knowledge`.
This activates an extra constraint that checks every `EmbeddingProjection`
object for a valid `represents` relation to an existing source object.
A projection that references a non‑existent source (a fabricated citation)
is mechanically flagged, giving you a clear, machine‑readable diagnostic
instead of an undetected hallucination.

---

# Testing

```bash
python -m pytest -v
```

19+ tests, all passing.

---

# License

MIT