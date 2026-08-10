# AI Chat (`ai_chat`)

Send a chat turn to an LLM (currently Anthropic only) that has access
to a restricted set of cks-mcp tools, scoped to a single session.

The LLM can call tools (`query_subgraph`, `evolve_knowledge`, …); the
handler executes them server‑side and feeds results back to the LLM
until it produces a final text reply or the iteration cap is hit.

## Usage

```json
{
  "method": "tools/call",
  "params": {
    "name": "ai_chat",
    "arguments": {
      "session_id": "s1",
      "prompt": "Summarise the objects in this session."
    }
  }
}
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `session_id` | yes | Session to scope the chat turn to. Every tool call's session‑shaped argument is pinned to this value. |
| `messages` | no | Full conversation so far (Anthropic Messages API shape). If omitted, `prompt` is used to start a fresh conversation. |
| `prompt` | no | Shortcut for a new conversation with a single user message. Ignored if `messages` is non‑empty. |

## Response

```json
{
  "reply": "The session contains 5 objects: ...",
  "tool_calls": [
    {
      "name": "query_subgraph",
      "arguments": { "session_id": "s1" },
      "result": { "nodes": [...] },
      "is_error": false
    }
  ],
  "messages": [ ... ]
}
```

`messages` is the full updated history; pass it back as‑is on the next
turn — the tool is stateless between calls.

## Security

- Tools that manage the server/runtime itself (`migrate_storage`,
  `start_agent`, …) are denylisted and can never be called by the LLM.
- Every session‑shaped argument is overwritten with the caller's
  `session_id` — the LLM cannot target a different session.

## Limitations

- Supports both **Ollama** (local, no API key) and **Anthropic**.
- Provider is selected via `CKS_LLM_PROVIDER` (auto/ollama/anthropic), same as `construct_knowledge`.
- Maximum 8 tool‑calling iterations per turn.