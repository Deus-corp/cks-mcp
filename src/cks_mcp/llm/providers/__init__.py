"""
Shared, low-level LLM provider primitives (Ollama, Anthropic,
OpenAI-compatible, Google Gemini).

This package has no opinion about *what* system prompt to send or how
to interpret the result -- that stays with whichever tool imports
these primitives (``construct_knowledge``, ``ingest_document``, ...)
and layers its own prompt/parsing/merge logic on top. Factoring the
provider plumbing out here means the fiddly bits -- reachability
probing, urllib error handling, JSON-from-markdown extraction -- are
implemented once and shared, instead of drifting between copies as
each tool evolves independently.

One module per provider (``ollama``, ``anthropic``, ``openai_compatible``,
``google``), plus ``json_extract`` for the shared LLM-output-to-JSON
helper and ``_shared`` for internal-only plumbing (telemetry
recording). This ``__init__`` re-exports every provider's public
functions so existing callers -- ``from cks_mcp.llm import providers``
then ``providers.call_ollama(...)`` -- don't need to know which
submodule a given function actually lives in.

Environment variables (read by callers, not by this package, except
``CKS_OLLAMA_HOST``):
    CKS_OLLAMA_HOST   -- Ollama server URL (default: http://localhost:11434).
"""

from __future__ import annotations

from cks_mcp.llm.providers.anthropic import call_anthropic, call_anthropic_with_tools
from cks_mcp.llm.providers.google import (
    call_google,
    call_google_with_tools,
    google_api_key,
    google_base_url,
)
from cks_mcp.llm.providers.json_extract import extract_json
from cks_mcp.llm.providers.ollama import (
    call_ollama,
    call_ollama_with_tools,
    ollama_available,
    ollama_host,
)
from cks_mcp.llm.providers.openai_compatible import (
    call_openai_compatible_single_shot,
    call_openai_compatible_with_tools,
    openai_base_url,
)

__all__ = [
    "call_anthropic",
    "call_anthropic_with_tools",
    "call_google",
    "call_google_with_tools",
    "call_ollama",
    "call_ollama_with_tools",
    "call_openai_compatible_single_shot",
    "call_openai_compatible_with_tools",
    "extract_json",
    "google_api_key",
    "google_base_url",
    "ollama_available",
    "ollama_host",
    "openai_base_url",
]
