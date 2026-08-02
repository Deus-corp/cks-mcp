"""Input schema definitions for the visualize_graph tool(s).

Separated from handler.py so the JSON Schema can be reviewed/edited
without touching implementation code.
"""

from __future__ import annotations

VISUALIZE_GRAPH_SCHEMA = {
    "name": "visualize_graph",
    "description": "Export a subgraph as a Mermaid diagram. Many MCP clients render "
    "Mermaid natively; if yours doesn't, the raw Mermaid text is still "
    "useful as structured output. Two modes: 'structure' (default) shows "
    "objects connected by CanonicalRelations, via query_subgraph -- use "
    "this after query_subgraph to show the structure. 'inference' shows "
    "the directed reasoning chain(s) behind one or more objects instead "
    "-- InferenceSteps connecting premises to a conclusion, via "
    "explain_inference -- use this after explain_knowledge(object_id=...) "
    "to show *why* something is believed, not just what it's linked to.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The session to visualize.",
            },
            "mode": {
                "type": "string",
                "enum": ["structure", "inference"],
                "description": "'structure' (default) walks CanonicalRelations via "
                "query_subgraph. 'inference' walks InferenceStep chains via "
                "explain_inference -- requires a Core that supports it "
                "(see explain_knowledge). 'depth' is ignored in inference mode: "
                "explain_inference always walks each target's full chain, back "
                "to base facts or a cycle/max-depth stub.",
            },
            "seed_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional. In 'structure' mode: object IDs to start "
                "from, defaults to all objects. In 'inference' mode: object IDs to "
                "explain, defaults to every distinct conclusion currently drawn by "
                "an active InferenceStep.",
            },
            "depth": {
                "type": "integer",
                "description": "How many hops to expand. Default 1. Structure mode only.",
            },
            "max_objects": {
                "type": "integer",
                "description": "Max objects/steps to include. Default 20.",
            },
            "include_superseded": {
                "type": "boolean",
                "description": "Inference mode only. When true, also render each "
                "target's revision history: InferenceSteps that once concluded it "
                "and have since been superseded, dashed and linked to whatever "
                "superseded them. Default false.",
            },
        },
        "required": ["session_id"],
    },
}