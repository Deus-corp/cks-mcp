# AI Chat (`ai_chat`)

Send a chat turn to an LLM (Ollama, Anthropic, Google Gemini, or any
OpenAI-compatible endpoint) that has access to a restricted set of
cks-mcp tools, scoped to a single session.

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

- Supports tool-calling against **Ollama** (local, no API key),
  **Anthropic**, **Google Gemini** (native `generateContent`, so
  `thoughtSignature` round-trips correctly on function-calling turns),
  and any **OpenAI-compatible** endpoint (OpenAI, Groq, DeepSeek,
  Together, LM Studio, vLLM, …), all routed through the shared
  `LLMClient`.
- Provider is selected via `CKS_LLM_PROVIDER`
  (`auto`/`ollama`/`anthropic`/`google`/`openai_compatible`). `auto`
  only ever picks Ollama (if reachable) or Anthropic (if
  `ANTHROPIC_API_KEY` is set) — `google` and `openai_compatible` must
  be selected explicitly, since their model/key/base-URL combination
  can't be guessed safely.
- Google requires `CKS_GOOGLE_API_KEY` (or `GOOGLE_API_KEY` as a
  fallback) and reads the model from `CKS_GOOGLE_MODEL` (default
  `gemini-2.5-flash`).
- Maximum 8 tool‑calling iterations per turn.