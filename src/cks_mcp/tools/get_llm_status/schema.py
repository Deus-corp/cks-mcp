"""Input schema definition for the get_llm_status tool.

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code (same convention every other
tool package in this codebase follows).
"""

from __future__ import annotations

GET_LLM_STATUS_SCHEMA = {
    "name": "get_llm_status",
    "description": (
        "Report which LLM provider ai_chat and construct_knowledge would "
        "currently use, and whether it's actually reachable/configured -- "
        "for a client UI to show without ever seeing ANTHROPIC_API_KEY or "
        "other provider env vars itself (see cks-mcp ADR-011 §6). Read-"
        "only; the only network call this makes is a cheap Ollama "
        "reachability probe (GET {CKS_OLLAMA_HOST}/api/tags), no chat/"
        "completion calls to either provider. Returns "
        "{'provider': 'ollama'|'anthropic'|'none', "
        "'ollama_available': bool, 'anthropic_configured': bool, "
        "'model': str | null}. 'provider' follows the same "
        "CKS_LLM_PROVIDER=auto|ollama|anthropic resolution "
        "construct_knowledge uses: an explicit CKS_LLM_PROVIDER wins "
        "outright, otherwise Ollama is preferred if reachable, then "
        "Anthropic if ANTHROPIC_API_KEY is set, else 'none'. 'model' is "
        "the model that provider would use (CKS_OLLAMA_MODEL / "
        "CKS_ANTHROPIC_MODEL / CKS_LLM_MODEL), or null when provider is "
        "'none'. Takes no session_id -- provider config is server-wide, "
        "not per-session."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {},
        "required": [],
        # No accepted parameters -- explicit for strict JSON Schema
        # validators (e.g. Google Gemini function-calling) so an empty
        # object isn't ambiguous with "any object shape allowed".
        "additionalProperties": False,
    },
}
