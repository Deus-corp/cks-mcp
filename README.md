# CKS MCP Server

> Model Context Protocol server for Canonical Knowledge Structure.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-26%20passing-brightgreen)
[![PyPI](https://img.shields.io/pypi/v/cks-mcp)](https://pypi.org/project/cks-mcp/)

`cks-mcp` is an MCP (Model Context Protocol) server that gives LLMs
a **canonical knowledge backbone**. It exposes five tools —
`validate_knowledge`, `serialize_knowledge`, `explain_knowledge`,
`evolve_knowledge`, and `verify_source` — backed by the deterministic,
immutable semantics of `cks-core` and the operational management of
`cks-runtime`.

Every tool call creates a **Runtime Session** and **Transaction**,
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

LLMs generate plausible but unverified statements. `cks-mcp` gives them
a **canonical knowledge backbone**: every piece of information must be
explicitly structured, validated against formal constraints, and
traceable to its origin.

- **Eliminate citation hallucinations** — optional extensions like
  `embedding_projection` mechanically detect references to non-existent
  sources.
- **Ensure verification integrity** — the `verify_source` tool performs
  a real HTTP check and cryptographically signs the result. Any
  `VerificationRecord` without a valid signature is automatically
  rejected, even if the model fails to request the check.
- **Full audit trail** — every operation is captured in an immutable
  version history, providing complete accountability for AI-generated
  knowledge.

---

# Installation

```bash
pip install cks-mcp
```

The server requires `cks-runtime` (which includes `cks-core`) as a dependency.

---

# Quick Start

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
   After restart, a connector icon will appear – `cks-mcp` with five tools
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
| `validate_knowledge` | Validate a Knowledge Structure and return diagnostics. Supports opt‑in extensions (`embedding_projection`, `verification_record`). Provenance of `VerificationRecord` objects is checked automatically. |
| `serialize_knowledge` | Serialize a Knowledge Structure into canonical JSON. |
| `explain_knowledge` | Produce a semantic explanation of a Knowledge Structure. |
| `evolve_knowledge` | Apply Genesis/Decay operators to evolve a structure. |
| `verify_source` | Perform a real HTTP request to check a URL's availability and create a cryptographically signed `VerificationRecord`. This is the only legitimate way to create verification records. |

---

# Usage Examples

## Validate a structure with citation-hallucination detection

Pass `"extensions": ["embedding_projection"]` to `validate_knowledge`.
This activates an extra constraint that checks every `EmbeddingProjection`
object for a valid `represents` relation to an existing source object.
A projection that references a non‑existent source (a fabricated citation)
is mechanically flagged.

## Validate a structure with verification integrity

When you use `verify_source` to check a URL, the resulting
`VerificationRecord` is cryptographically signed. Any
`VerificationRecord` found in a structure without a valid signature
is automatically rejected, **even if the model does not explicitly
request the verification extension**. This prevents LLMs from
bypassing the check by simply omitting a parameter.

## Basic validation

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

---

# Security and Provenance

`verify_source` includes built-in protections:
- **SSRF prevention**: URLs are validated against a strict allowlist;
  private, loopback, and cloud metadata IPs are blocked. DNS rebinding
  attacks are neutralised by pinning the connection to the IP address
  resolved during the safety check.
- **Cryptographic signing**: every verification record is signed with a
  process-local HMAC. `validate_knowledge` unconditionally verifies this
  signature, so a hand‑written `VerificationRecord` can never pass as
  genuine.

---

# Testing

```bash
python -m pytest -v
```

26+ tests, all passing.

---

# License

MIT