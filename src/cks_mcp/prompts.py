"""
MCP Prompts for CKS – ready‑to‑use workflows for Claude Desktop.

When a client asks for prompts/list, the server returns a set of
templated scenarios.  prompts/get fills the selected template with
user‑supplied arguments and returns a concrete user message that
Claude can process immediately.
"""

from __future__ import annotations

from typing import Any


PROMPTS = {
    "create_knowledge_graph": {
        "name": "create_knowledge_graph",
        "description": "Create a validated knowledge graph about a topic",
        "arguments": [
            {
                "name": "topic",
                "description": "The topic to create a knowledge graph about (e.g. 'the water cycle')",
                "required": True,
            },
        ],
    },
    "verify_claim": {
        "name": "verify_claim",
        "description": "Verify a claim by checking a real URL and signing the result",
        "arguments": [
            {
                "name": "claim",
                "description": "The claim to verify (e.g. 'Dark matter consists of WIMPs')",
                "required": True,
            },
            {
                "name": "url",
                "description": "The URL of the source to check",
                "required": True,
            },
        ],
    },
    "explore_subgraph": {
        "name": "explore_subgraph",
        "description": "Extract the local neighbourhood around an object in a knowledge graph",
        "arguments": [
            {
                "name": "session_id",
                "description": "The session ID of the knowledge graph to explore",
                "required": True,
            },
            {
                "name": "seed_id",
                "description": "The object ID to start the exploration from",
                "required": True,
            },
            {
                "name": "depth",
                "description": "How many hops to explore (default: 1)",
                "required": False,
            },
        ],
    },
    "branch_and_merge": {
        "name": "branch_and_merge",
        "description": "Demonstrate a branching and merging workflow on a knowledge graph",
        "arguments": [
            {
                "name": "session_id",
                "description": "The session ID of the knowledge graph to branch from",
                "required": True,
            },
        ],
    },
}


def list_prompts() -> list[dict[str, Any]]:
    """Return a list of MCP prompt descriptors."""
    return [
        {
            "name": prompt["name"],
            "description": prompt["description"],
            "arguments": prompt["arguments"],
        }
        for prompt in PROMPTS.values()
    ]


def get_prompt(name: str, arguments: dict[str, str] | None = None) -> dict[str, Any] | None:
    """Return a concrete MCP prompt message for the given name and arguments."""
    prompt = PROMPTS.get(name)
    if prompt is None:
        return None

    args = arguments or {}

    # Map each prompt name to the text that will be sent to Claude
    templates = {
        "create_knowledge_graph": (
            f"Use cks-mcp to create a knowledge graph about {args.get('topic', 'the topic')} "
            "with at least 5 objects and 3 relations. Then validate it."
        ),
        "verify_claim": (
            f"Use cks-mcp to verify this claim: \"{args.get('claim', 'the claim')}\". "
            f"Check the source at {args.get('url', 'the URL')} and create a signed VerificationRecord."
        ),
        "explore_subgraph": (
            f"Use cks-mcp to query a subgraph. Session ID: {args.get('session_id', 'SESSION_ID')}, "
            f"seed ID: {args.get('seed_id', 'SEED_ID')}, depth: {args.get('depth', '1')}."
        ),
        "branch_and_merge": (
            f"Use cks-mcp to create a branch from session {args.get('session_id', 'SESSION_ID')}, "
            "evolve both the original and the branch differently, then merge the branch back."
        ),
    }

    text = templates.get(name, "")
    return {
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": text,
                },
            }
        ]
    }