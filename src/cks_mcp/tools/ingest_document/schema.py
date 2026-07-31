"""Input schema definitions for the ingest_document tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

INGEST_DOCUMENT_SCHEMA = {
    "name": "ingest_document",
    "description": "Fetch a public URL, extract its title, description and key topics, "
    "and return a Knowledge Structure representing the document. "
    "The document object is linked via 'mentions' relations to Topic "
    "objects for each extracted keyword. SSRF protection is applied, "
    "so private/internal URLs are refused.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The publicly accessible URL to fetch."}
        },
        "required": ["url"],
    },
}
