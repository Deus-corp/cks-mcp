# Getting Started

## What is cks-mcp?

`cks-mcp` is an MCP server: it lets an LLM client (Claude Desktop, or any
other MCP-speaking client) validate, evolve, branch, merge, and search a
**Canonical Knowledge Structure** through 24 tools, instead of holding
that knowledge loosely in its own context. See [the overview](index.md)
for why that matters.

## Installation

```bash
pip install cks-mcp
```

This pulls in `cks-runtime` (which in turn depends on `cks-core`) as a
dependency — you don't need to install those separately unless you're
developing against them directly.

Requires **Python 3.12+**.

## Optional environment variables

| Variable | Used by | Purpose |
|----------|---------|---------|
| `CKS_EMBEDDING_PROVIDER` | `search_semantic` | `"fastembed"` (default) for local, token‑free embeddings; `"huggingface"` for the HuggingFace Inference API. |
| `HF_TOKEN` | `search_semantic` | Required only when `CKS_EMBEDDING_PROVIDER=huggingface`. |
| `CKS_LLM_PROVIDER` | `construct_knowledge` | `"auto"` (default — prefers a local Ollama server, falls back to Anthropic), `"ollama"`, or `"anthropic"`. |
| `ANTHROPIC_API_KEY` | `construct_knowledge` | Required only for the `"anthropic"` provider. |
| `CKS_LLM_MODEL` | `construct_knowledge` | Overrides the Anthropic model (default `claude-sonnet-4-6`). |
| `CKS_OLLAMA_MODEL` | `construct_knowledge` | Overrides the Ollama model (default `llama3.2`). |
| `CKS_OLLAMA_HOST` | `construct_knowledge` | Ollama server URL (default `http://localhost:11434`). |
| `CKS_LLM_MAX_TOKENS` | `construct_knowledge` | Overrides max-tokens (default `4096`). |
| `CKS_MCP_DATA_DIR` | server startup | Overrides `~/.cks-mcp` (DB + provenance secret). |
| `CKS_MCP_SECRET` | provenance signing | Overrides the auto‑generated HMAC secret. |

Instead of exporting these in your shell, you can drop them into
`~/.cks-mcp/.env` (one `KEY=value` per line) — the server reads that file
on startup if it exists. This is convenient for `HF_TOKEN` and
`ANTHROPIC_API_KEY` in particular, since Claude Desktop launches the server
without your shell's environment.

## Connect to Claude Desktop

1. Install all three packages into a single virtual environment:

   ```bash
   python3 -m venv cks-env
   source cks-env/bin/activate
   pip install cks-core cks-runtime cks-mcp
   ```

2. Open Claude Desktop → **Settings → Developer → Edit Config**, and add:

   ```json
   {
     "mcpServers": {
       "cks-mcp": {
         "command": "/absolute/path/to/cks-env/bin/cks-mcp"
       }
     }
   }
   ```

3. Save and fully restart Claude Desktop (quit, then reopen). A connector
   icon for `cks-mcp` (24 tools) should appear.

Any other MCP client that speaks JSON-RPC over stdio works the same way —
point it at the `cks-mcp` executable.

## Your First Session

A typical workflow is: create something, inspect it, change it, and look
at its history. Here's the shortest version, as raw `tools/call` requests
(what your MCP client sends under the hood when you type a plain-English
request):

**1. Validate a structure — this also creates your session:**

```json
{
  "method": "tools/call",
  "params": {
    "name": "validate_knowledge",
    "arguments": {
      "json_data": "{\"objects\":[{\"identity\":{\"id\":\"obj-1\",\"type\":\"Definition\",\"name\":\"Photosynthesis\"},\"structure\":{}}]}"
    }
  }
}
```

The response includes a `session_id` — keep it, every following call uses it.

**2. Change it:**

```json
{
  "method": "tools/call",
  "params": {
    "name": "evolve_knowledge",
    "arguments": {
      "session_id": "<session_id from step 1>",
      "operations": [
        {"type": "add_object", "identity": {"id": "obj-2", "type": "Definition", "name": "Chlorophyll"}, "structure": {}},
        {"type": "add_relation", "identity": {"id": "rel-1", "type": "Relation", "name": "r"}, "participants": ["obj-1", "obj-2"], "relation_type": "requires"}
      ]
    }
  }
}
```

**3. See what changed:**

```json
{"method": "tools/call", "params": {"name": "list_versions", "arguments": {"session_id": "<session_id>"}}}
```

From here, `query_subgraph` or `visualize_graph` let you look at the
structure itself; `search_semantic` lets you find things in it by meaning
once it grows past what you can hold in your head. The full set of 24
tools, grouped by what they're for, is in the
[Tools Reference](tools/index.md).

**In practice**, you don't write raw `tools/call` JSON yourself — in Claude
Desktop, just start a message with **"Use cks-mcp to…"** and the model
picks the right tool and arguments for you.

**To use semantic search without any API keys** — which is now the
default — leave `CKS_EMBEDDING_PROVIDER` unset (`fastembed`) and the
server will download a small (~90 MB) sentence‑transformers model
once on first use, then run fully offline from that point on.

**To use `construct_knowledge` without any API keys**, run
[Ollama](https://ollama.com) on `localhost` — `construct_knowledge`
auto‑detects it and uses a local `llama3.2` model by default, no
`ANTHROPIC_API_KEY` needed.

## Running the Test Suite

```bash
git clone https://github.com/Deus-corp/cks-mcp.git
cd cks-mcp
pip install -e ".[dev]"
python -m pytest -v
```

## Next Steps

- [Tools Reference](tools/index.md) — every tool, grouped by function.
- [Architecture](architecture/ARCHITECTURE.md) — how the server is put
  together and why, if you're extending or embedding it.
