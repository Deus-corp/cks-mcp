# MCP Resources

Beyond its 24 tools, `cks-mcp` exposes every active session and its version
history as **MCP Resources** — read-only, URI-addressable views a client
can list and read directly, without a tool call. Useful for a client UI
that wants to browse what exists without asking an LLM to call
`list_versions` on its behalf.

## URI structure

| URI | Returns |
|-----|---------|
| `cks://sessions` | JSON list of every active session: `session_id`, `created` (timestamp of its first version), `version_count`. |
| `cks://sessions/{session_id}` | The session's **current** Knowledge Structure, canonical JSON. |
| `cks://sessions/{session_id}/versions` | JSON list of the session's version history: `version_id`, `created_at`, `transaction_id`, `metadata` (same shape `list_versions` returns). |
| `cks://sessions/{session_id}/versions/{version_id}` | The Knowledge Structure **as it was** at that specific historical version. |

All four are read-only and mirror data available through tools
(`list_versions`, `serialize_knowledge`) — Resources exist for clients that
prefer resource-style browsing over issuing a tool call for a plain read.

## Example

An MCP client's `resources/list` call returns descriptors like:

```json
{
  "uri": "cks://sessions/sess-abc123",
  "name": "Session sess-abc1…",
  "description": "Knowledge Structure of session sess-abc123",
  "mimeType": "application/json"
}
```

`resources/read` on that URI returns the same canonical JSON
`serialize_knowledge` would, for the session's current state.

## Notes

- A URI for a session or version that doesn't exist (deleted, or never
  existed) resolves to no content — the client sees an empty read rather
  than an error.
- `cks://sessions/{session_id}/versions/{version_id}` reconstructs the
  structure at that version on read; it isn't a separate stored copy, so it
  stays in sync automatically as the version history for other sessions
  changes.
- Resources reflect the same underlying `Runtime` a tool call would — a
  session created via `validate_knowledge` in the same server process is
  immediately visible as a Resource, with no separate registration step.

See [Tools Reference](../tools/index.md) for the tool-based equivalents of
each of these reads, and [Prompts](prompts.md) for the other MCP-native
feature `cks-mcp` exposes alongside its tools.
