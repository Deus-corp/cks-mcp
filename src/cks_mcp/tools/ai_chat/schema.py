"""Input schema definition for the ai_chat tool.

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code (same convention every other
tool package in this codebase follows).
"""

from __future__ import annotations

AI_CHAT_SCHEMA = {
    "name": "ai_chat",
    "description": (
        "Send a chat turn to an LLM with access to a restricted set of "
        "cks-mcp tools, scoped to 'session_id'. The LLM may call tools "
        "(query_subgraph, evolve_knowledge, ...); this handler executes "
        "them server-side and feeds results back to the LLM until it "
        "produces a final text reply or the iteration cap is hit. Every "
        "tool call the LLM makes has its session-shaped argument "
        "overwritten with 'session_id' before execution -- the LLM "
        "cannot target a different session (see cks-mcp ADR-011 §3). "
        "Returns {'reply': str, 'tool_calls': [...], 'messages': [...]} "
        "-- 'messages' is the full updated history; pass it back as-is "
        "on the next turn (this tool is stateless between calls). If "
        "the iteration cap is hit before a final answer, the result "
        "also includes 'truncated': true alongside the human-readable "
        "'reply', so callers can detect and retry this specific, "
        "retriable condition without string-matching the reply text. "
        "The LLM provider is selected via CKS_LLM_PROVIDER='auto' "
        "(default) | 'ollama' | 'anthropic', same convention as "
        "construct_knowledge: 'auto' uses a local Ollama server if "
        "one is reachable, otherwise Anthropic. 'ollama' requires a "
        "tool-calling-capable model (e.g. llama3.1+, qwen2.5) pulled "
        "and served locally (CKS_OLLAMA_HOST, CKS_OLLAMA_MODEL); "
        "'anthropic' requires ANTHROPIC_API_KEY. If no provider is "
        "available, returns {'error': 'llm_provider_unavailable', "
        "'message': ...} instead of raising (see ADR-011 §6)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": (
                    "The session this chat turn is scoped to. Every tool "
                    "call the LLM makes during this turn has its "
                    "session-shaped argument forcibly overwritten with "
                    "this value before execution."
                ),
            },
            "messages": {
                "type": "array",
                "description": (
                    "Full conversation so far, including the new user "
                    "turn, using the Anthropic Messages API content "
                    "shape ({'role': 'user'|'assistant', 'content': "
                    "str | block[]}). Empty/omitted 'messages' plus a "
                    "'prompt' starts a fresh conversation."
                ),
            },
            "prompt": {
                "type": "string",
                "description": (
                    "Shorthand for starting a new conversation with a "
                    "single user message; ignored if 'messages' is set "
                    "and non-empty."
                ),
            },
        },
        "required": ["session_id"],
    },
}
