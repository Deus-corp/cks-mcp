"""Input schema definitions for the construct_knowledge tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

CONSTRUCT_KNOWLEDGE_SCHEMA = {
    "name": "construct_knowledge",
    "description": "Build a Canonical Knowledge Structure from free-form text using an LLM. "
    "The LLM extracts entities and relationships, generates a valid CKS JSON "
    "payload, which is then parsed and validated before being persisted as a "
    "new session. Requires ANTHROPIC_API_KEY to be set in the environment. "
    "Returns 'session_id', 'version_id', and the serialized structure. "
    "Use 'hint' to direct the extraction toward specific aspects of the text.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Free-form text to extract a Knowledge Structure from.",
            },
            "hint": {
                "type": "string",
                "description": (
                    "Optional. A short description of which aspects to focus on "
                    "(e.g. 'focus on causal relations between diseases and symptoms')."
                ),
            },
            "model": {
                "type": "string",
                "description": (
                    "Optional. Anthropic model to use. Defaults to the "
                    "CKS_LLM_MODEL environment variable, or 'claude-sonnet-4-6'."
                ),
            },
            "max_tokens": {
                "type": "integer",
                "description": (
                    "Optional. Max tokens for the LLM response. "
                    "Defaults to CKS_LLM_MAX_TOKENS env var, or 4096."
                ),
            },
        },
        "required": ["text"],
    },
}
