"""Input schema definitions for the search_semantic tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

SEARCH_SEMANTIC_SCHEMA = {
    "name": "search_semantic",
    "description": "Semantically search the Knowledge Structure of a session. "
    "Provide a natural language query; if the storage backend has "
    "a vector index (embeddings generated via the background "
    "outbox worker), matching seed objects are found "
    "automatically. Pass explicit 'seed_ids' instead when you "
    "already know which objects to expand around, or as a "
    "fallback if no embeddings have been generated yet for this "
    "session. The tool expands the neighbourhood around the "
    "matched seeds using query_subgraph. "
    "Use this when you don't know exact object IDs but have a "
    "description of what you're looking for.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session to search in.",
            },
            "query": {
                "type": "string",
                "description": "Natural language description of what to find.",
            },
            "seed_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional. List of object IDs to start the subgraph expansion from. Omit to use vector search automatically; required as a fallback if the storage backend has no embeddings for this session yet.",
            },
            "top_k": {
                "type": "integer",
                "description": "Max number of seed objects to use (default 3).",
            },
            "depth": {
                "type": "integer",
                "description": "How many hops to expand around each seed (default 1).",
            },
            "min_score": {
                "type": "number",
                "description": "Minimum cosine similarity score (0.0 to 1.0). Results below this threshold are excluded. Default 0.0 (no filtering).",
            },
        },
        "required": ["session_id", "query"],
    },
}
