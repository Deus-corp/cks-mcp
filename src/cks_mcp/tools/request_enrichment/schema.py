from __future__ import annotations

REQUEST_ENRICHMENT_SCHEMA = {
    "name": "request_enrichment",
    "description": (
        "Enqueue an enrichment_request task into the persistent outbox, asking "
        "the Enrichment Agent (see cks-enrichment-agent console script) to "
        "search external sources for more context about a given object and "
        "ingest what it finds back into the graph. Requires a storage backend "
        "that supports the outbox (SQLite or Postgres). Returns "
        "'supported': false under the default in-memory backend. "
        "The task will be picked up by the next cks-enrichment-agent poll cycle."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session containing the object to enrich."
            },
            "object_id": {
                "type": "string",
                "description": "The id of the object that needs more context."
            },
            "query": {
                "type": "string",
                "description": (
                    "Optional. A custom search query to use instead of the "
                    "object's own name. E.g. 'latest clinical trial results for "
                    "drug X' when the object is named 'Drug X'."
                ),
            },
        },
        "required": ["session_id", "object_id"],
    },
}