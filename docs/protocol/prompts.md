# MCP Prompts

`cks-mcp` also exposes four **MCP Prompts** — ready-made workflow templates
a client can list (`prompts/list`) and fill in (`prompts/get`) to get a
concrete instruction back, without the user having to know which tools to
chain together or in what order.

A prompt doesn't call any tools itself: `prompts/get` returns a single
user-role text message, built from the prompt's arguments, that the
connected model then acts on normally — using whichever of the 24 tools
that instruction implies.

## Available prompts

| Name | Arguments | What it produces |
|------|-----------|-------------------|
| `create_knowledge_graph` | `topic` (required) | An instruction to build a validated knowledge graph (≥5 objects, ≥3 relations) about `topic`, then validate it. |
| `verify_claim` | `claim` (required), `url` (required) | An instruction to verify `claim` against `url` and produce a signed `VerificationRecord`. |
| `explore_subgraph` | `session_id` (required), `seed_id` (required), `depth` (optional, default `1`) | An instruction to query the subgraph around `seed_id` in `session_id` at the given depth. |
| `branch_and_merge` | `session_id` (required) | An instruction to branch `session_id`, evolve the original and the branch differently, then merge the branch back. |

## Example

`prompts/get` with `name: "verify_claim"` and
`arguments: {"claim": "Dark matter consists of WIMPs", "url": "https://example.org/paper"}`
returns:

```json
{
  "messages": [
    {
      "role": "user",
      "content": {
        "type": "text",
        "text": "Use cks-mcp to verify this claim: \"Dark matter consists of WIMPs\". Check the source at https://example.org/paper and create a signed VerificationRecord."
      }
    }
  ]
}
```

The model receiving that message would typically call `verify_source`,
then merge the resulting `VerificationRecord` into the relevant session via
`evolve_knowledge` — but the prompt itself only supplies the instruction,
not the tool sequence; that's still up to the model.

## Why these four

Each prompt corresponds to one of the workflows [Getting Started](../getting-started.md)
and [Tools Reference](../tools/index.md) walk through by hand:
knowledge construction, provenance verification, graph exploration, and
branching — a template for the four most common "which tools do I even
call for this" starting points. If you find yourself typing the same
multi-tool instruction repeatedly, a fifth prompt in `PROMPTS` (in
`src/cks_mcp/prompts.py`) is the natural place to save it.
