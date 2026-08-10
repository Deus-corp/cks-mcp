"""Input schema definition for the list_llm_models tool.

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code (same convention every other
tool package in this codebase follows).
"""

from __future__ import annotations

LIST_LLM_MODELS_SCHEMA = {
    "name": "list_llm_models",
    "description": (
        "List the models available for whichever LLM provider ai_chat/"
        "construct_knowledge would currently use (same provider "
        "resolution as get_llm_status), so a client UI can offer a model "
        "picker before calling ai_chat with its optional 'model' "
        "argument. For provider 'ollama' this queries the local Ollama "
        "server (GET {CKS_OLLAMA_HOST}/api/tags) and returns whatever "
        "models are actually installed there; for 'anthropic' and "
        "'openai_compatible' it returns a short hardcoded list of "
        "current popular models (no network call -- neither provider "
        "exposes a model-list endpoint this server can safely reach "
        "without an API key); for 'none' it returns an empty list. "
        "Returns {'provider': 'ollama'|'anthropic'|'openai_compatible'|"
        "'none', 'models': [{'name': str}, ...]}. Read-only. Takes no "
        "session_id -- provider config is server-wide, not per-session."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}
