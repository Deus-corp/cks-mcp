"""Input schema definitions for the ingest_document tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

INGEST_DOCUMENT_SCHEMA = {
    "name": "ingest_document",
    "description": (
        "Fetch a public URL, extract its title, description, keywords, and "
        "structured content (sections, tables, lists, metadata from JSON-LD / "
        "OpenGraph / microdata). Returns a Knowledge Structure with Document, "
        "Section, Table, List, Metadata, and Topic objects. If 'use_llm' is "
        "true, the extracted content is sent to an LLM (same provider "
        "auto-selection as construct_knowledge) to build a richer graph."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The publicly accessible URL to fetch."
            },
            "use_llm": {
                "type": "boolean",
                "description": (
                    "If true, send the extracted structured content to an LLM "
                    "to build a full knowledge graph. Defaults to false."
                ),
                "default": False,
            },
            "model": {
                "type": "string",
                "description": (
                    "Optional. LLM model name to use when use_llm is true. "
                    "Defaults to the provider's default (e.g. llama3.2 for "
                    "Ollama, claude-sonnet-4-6 for Anthropic)."
                ),
            },
            "max_tokens": {
                "type": "integer",
                "description": (
                    "Optional. Max tokens for the LLM response. Defaults to "
                    "CKS_LLM_MAX_TOKENS or 4096."
                ),
            },
        },
        "required": ["url"],
    },
}