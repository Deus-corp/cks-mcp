# ADR-011: `ai_chat` Tool

**Status:** Proposed
**Related:** cks-studio ADR-001 (AI Assistant Chat Panel — owns the
client-side page/store design this tool serves), ADR-007
(CKSAgentOrchestrator — a longer-running multi-agent pipeline; `ai_chat`
is a single synchronous chat turn, not that pipeline), ADR-009/ADR-010
(Sweeper/Process Control Tools — same split precedent: this ADR owns the
server-side tool contract, cks-studio ADR-001 owns the UI)

## Context

`construct_knowledge` already proves the pattern of a tool that calls an
LLM and turns its output into graph writes, but it's single-purpose
(text → one `add_object`/`add_relation` batch) and single-shot (no back
and forth, no tool selection by the model). cks-studio ADR-001 needs
something categorically different: an LLM that can freely choose among
this server's ~60 registered tools across a multi-turn conversation,
executing them in-process against the live `Runtime`, so a human's
prompt in cks-studio can result in real graph reads/writes without a
second implementation of the tool-dispatch table living in the browser.

## Decision

One tool, `ai_chat(session_id, messages, prompt?)`, implementing a
bounded agentic loop:

1. **Tool exposure is a denylist, not an allowlist.** Every tool in
   `registry.py`'s `TOOLS` dict is offered to the LLM except a small,
   explicit set that manages the server/runtime itself rather than the
   knowledge graph: `migrate_storage`, `export_storage`,
   `import_storage`, `list_plugins`, `register_graph` (writes the public
   gallery — human-only for v1), and the three Agent Panel control tools
   (`start_agent`, `stop_agent`, `request_process_stop` — background
   process control from a chat LLM is out of scope, not because it's
   dangerous exactly, but because it has nothing to do with the
   knowledge graph a chat session is about). New tools added to the
   registry are exposed to the LLM by default; a tool author who adds
   something server-management-shaped must remember to add it to the
   denylist — same kind of manually-maintained constant
   `GRAPH_MUTATING_TOOLS` is on the cks-studio side (ADR-001), not a
   perfect guarantee, but consistent with how narrow this project's
   other manually-maintained tool lists already are.
2. **Every session-shaped argument is pinned to `ai_chat`'s own
   `session_id`, overwriting whatever the LLM supplied**, before the
   handler runs — checked by inspecting the target tool's `inputSchema`
   for a `session_id` property. This is a hard rule, not a validation
   warning: the LLM's own reasoning is not a trust boundary, and a
   prompt-injected or simply confused tool call naming a different
   session must be structurally incapable of touching it. (`list_agents`
   /`list_processes`-style tools that take no `session_id` at all are
   unaffected — they were already global/read-only before this tool
   existed.)
3. **The loop is capped at a fixed number of iterations** (8 for v1, one
   round-trip to the LLM per iteration) rather than running until the
   model stops asking for tools on its own. An LLM that gets stuck in a
   call-a-tool/re-evaluate cycle should fail loudly with "reached the
   iteration limit" in the chat, not run up an unbounded number of
   Anthropic API calls against one human's single chat message.
4. **Handler exceptions become `tool_result` content with
   `is_error: true`, fed back to the LLM, not raised out of `ai_chat`
   itself.** The LLM sees its own tool call failed (e.g. `evolve_knowledge`
   returning `validation_failed`) and can retry with corrected
   arguments or explain the failure to the human — the same "business
   errors are data, not exceptions" convention `evolve_knowledge`
   already established for its own callers (see that handler's own
   docstring).
5. **No conversation state is kept server-side.** `ai_chat` takes the
   full `messages` array on every call and returns the updated array;
   cks-studio ADR-001 owns persisting it (in a zustand store, not a new
   `cks-runtime` table — see that ADR's §2 for the reasoning). This
   keeps `ai_chat` itself trivially stateless and horizontally
   replaceable, same as every other tool in this registry.
6. **v1 requires `ANTHROPIC_API_KEY`; no Ollama path yet.** Anthropic's
   Messages API tool-use (`tools`, `tool_choice`, `tool_use`/
   `tool_result` content blocks) is what this loop is built against.
   `llm_providers.py`'s existing Ollama support only covers
   `/api/generate` (used by `construct_knowledge`'s single-shot
   extraction), which has no tool-calling shape — Ollama's `/api/chat`
   with a `tools` array is a different endpoint and a separate,
   deliberately deferred piece of work (Milestone 2). `ai_chat` fails
   fast with a clear "set ANTHROPIC_API_KEY" message rather than
   silently falling back to a provider that can't do tool-calling at
   all.

## Consequences

**Positive:**
- Reuses the exact tool implementations every other MCP client already
  calls — no parallel "LLM-safe" reimplementation of `evolve_knowledge`
  et al. to keep in sync.
- Session-pinning (Decision 2) means `ai_chat` cannot become a confused-
  deputy path into a different session's graph, independent of prompt
  content.
- Stateless design (Decision 5) means no new persistence to design,
  migrate, or garbage-collect for v1.

**Negative / accepted tradeoffs:**
- Denylist maintenance (Decision 1) is a manual step future tool authors
  can forget; revisit as an allowlist or a schema-level
  `exposable_to_llm: bool` flag if the tool count or the cost of a
  forgotten entry grows.
- Anthropic-only (Decision 6) means deployments running
  `CKS_LLM_PROVIDER=ollama`-only cannot use the Chat tab until Milestone
  2 ships. This should be stated plainly in cks-studio's Settings page,
  not discovered as a runtime error.
- Fixed iteration cap (Decision 3) means a genuinely complex multi-step
  request could hit the cap before finishing; the failure mode is a
  clear message in the chat, not silent truncation, so the human can
  re-prompt with a narrower ask.

## Implementation Plan

See cks-studio ADR-001's Implementation Plan (Milestone 1) for the full
`schema.py`/`handler.py` sketch and `registry.py` wiring — reproduced
there in full rather than duplicated here, since the two ADRs were
authored together and that plan already reflects this ADR's decisions
1–6 directly (denylist as `_DISALLOWED_TOOLS`, session pinning via
`_SESSION_ARG_NAME`, iteration cap as `_MAX_ITERATIONS`, error results
as `is_error` tool_result blocks).

One piece owned here that cks-studio ADR-001's sketch stubs out:
`call_anthropic_with_tools` in `llm_providers.py`, a new sibling to the
existing `call_anthropic`:

```python
# src/cks_mcp/llm_providers.py — new function, alongside call_anthropic

def call_anthropic_with_tools(
    *,
    messages: list[dict],
    tools: list[dict],
    model: str | None = None,
    max_tokens: int = 4096,
) -> dict:
    """POSTs to /v1/messages with 'tools' + 'tool_choice': 'auto'. Unlike
    call_anthropic (single-shot, text-in/text-out for construct_knowledge),
    this returns the raw response['content'] block list as-is (mixed
    text/tool_use blocks) -- ai_chat's loop needs the block structure,
    not a flattened string. Requires ANTHROPIC_API_KEY (see ADR-011 §6);
    raises RuntimeError with a clear message if unset, same convention
    call_anthropic already uses for its own missing-key case.
    """
    ...
```

Milestone 2 (SSE streaming, Ollama `/api/chat` tool-calling path) and
Milestone 3 (durable chat history) are cks-studio ADR-001's to own, since
both are driven by client-visible requirements (streaming UX, resuming a
session) rather than a server-side design gap.
