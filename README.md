# CKS MCP Server

> Model Context Protocol server for Canonical Knowledge Structure.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-50%20passing-brightgreen)
[![PyPI](https://img.shields.io/pypi/v/cks-mcp)](https://pypi.org/project/cks-mcp/)

`cks-mcp` is an MCP (Model Context Protocol) server that gives LLMs
a **canonical knowledge backbone**. It exposes the tools listed under
*Available Tools* below, backed by the deterministic,
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

# Quick Start

1. Install and connect to Claude Desktop (see [Installation](#installation)).
2. In the chat, start your message with **"Use cks-mcp to…"**.
3. Claude automatically picks the right tool from the 13 available — validation, evolution, branching, merging, source verification, subgraph queries, and more.
4. Every operation is logged, versioned, and stored in a persistent SQLite database.

**Just type "Use cks-mcp to..." and Claude does the rest. That's it.**
**No programming, no command line — just a conversation!**


![CKS Demo](demo/demo.gif)

  
*In the video above, Claude creates a validated knowledge graph about the water cycle from a single sentence, using `validate_knowledge` and `explain_knowledge`. Thirteen tools are ready for you: branching, merging, versioning, source verification, subgraph queries, and more — all triggered by plain English.*

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
- **Time-travel debugging** — `list_versions`, `revert_version`, and `compare_versions` give LLMs a full version-control system for knowledge, enabling safe rollbacks and change inspection.

---

# Installation

```bash
pip install cks-mcp
```

The server requires `cks-runtime` (which includes `cks-core`) as a dependency.

---

# Connect to Claude Desktop

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
   After restart, a connector icon will appear – `cks-mcp` with thirteen tools
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
| `verify_source` | Perform a real HTTP request to check a URL's availability and create a cryptographically signed `VerificationRecord`. |
| `list_versions` | List all available versions of a session's history. |
| `compare_versions` | Compute the structural difference between the current state of a session and a target version. |
| `revert_version` | Revert a session's Knowledge Structure to a specific previous version. |
| `merge_knowledge` | Three-way merge of knowledge structures with conflict detection. |
| `create_branch` | Fork a new session from an existing one, optionally from a specific historical version. |
| `merge_branch` | Session-aware three-way merge: merge a branch session into a target session, resolving the merge base automatically from the branch's recorded fork point. |
| `close_session` | Close a session, releasing it from the runtime (e.g. a branch already merged in). |
| `query_subgraph` | Extract a local k‑hop neighbourhood from a session's Knowledge Structure, with filters and optional budget. |

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

## Compare two versions

```json
{
  "method": "tools/call",
  "params": {
    "name": "compare_versions",
    "arguments": {
      "session_id": "...",
      "target_version_id": "..."
    }
  }
}
```

Response:

```json
{
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"session_id\": \"...\", \"target_version_id\": \"...\", \"changes\": [...]}"
      }
    ]
  }
}
```

## Branch, evolve independently, and merge back

Fork a session, evolve the branch and its parent independently, then
merge the branch back in:

```json
{"method": "tools/call", "params": {"name": "create_branch",
  "arguments": {"session_id": "trunk-session-id"}}}
```

```json
{"method": "tools/call", "params": {"name": "evolve_knowledge",
  "arguments": {"session_id": "branch-session-id", "operations": [...]}}}
```

```json
{"method": "tools/call", "params": {"name": "merge_branch",
  "arguments": {"target_session_id": "trunk-session-id",
                "source_session_id": "branch-session-id"}}}
```

A successful merge commits a new version of the target session and
returns its `serialized` structure and `version_id`. A conflicting
merge instead returns `"merged": false` with a `conflicts` list
(`object_id`, `base_state`, `target_state`, `source_state`) — resolve
each one on the target session with `evolve_knowledge`, then
`close_session` the branch once it's fully integrated.

---

## Query a subgraph

```json
{
  "method": "tools/call",
  "params": {
    "name": "query_subgraph",
    "arguments": {
      "session_id": "...",
      "seed_ids": ["obj-1"],
      "depth": 2,
      "max_objects": 10
    }
  }
}
```

Response (truncated example):

```json
{
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"subgraph\": \"...\", \"total_found_nodes\": 15, \"returned_nodes\": 10, \"is_truncated\": true, \"suggested_next_seed\": \"obj-7\"}"
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

50+ tests, all passing.

---

# License

MIT