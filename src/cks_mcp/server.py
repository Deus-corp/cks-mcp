"""
CKS MCP Server — JSON-RPC over stdio.

Implements the Model Context Protocol (MCP) to expose CKS tools
to LLM clients.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Callable, Dict, Optional

from .tools.validate import validate_knowledge
from .tools.query import query_relations
from .tools.compare import compare_structures
from .tools.evolve import evolve_knowledge
from .tools.derive import derive_knowledge


# Registry of available tools
TOOLS: Dict[str, Dict[str, Any]] = {
    "validate_knowledge": {
        "name": "validate_knowledge",
        "description": "Validate a canonical knowledge structure and return diagnostics.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "json_data": {
                    "type": "string",
                    "description": "A JSON string representing a Knowledge Structure.",
                },
            },
            "required": ["json_data"],
        },
    },
    "query_relations": {
        "name": "query_relations",
        "description": "Query all relations for a given entity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "json_data": {
                    "type": "string",
                    "description": "A JSON string representing a Knowledge Structure.",
                },
                "entity_id": {
                    "type": "string",
                    "description": "The canonical identity of the entity to query.",
                },
            },
            "required": ["json_data", "entity_id"],
        },
    },
    "compare_structures": {
        "name": "compare_structures",
        "description": "Compare two knowledge structures for semantic equivalence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "json_data_a": {
                    "type": "string",
                    "description": "A JSON string representing the first Knowledge Structure.",
                },
                "json_data_b": {
                    "type": "string",
                    "description": "A JSON string representing the second Knowledge Structure.",
                },
            },
            "required": ["json_data_a", "json_data_b"],
        },
    },
    "evolve_knowledge": {
        "name": "evolve_knowledge",
        "description": "Apply a sequence of structural operators to a knowledge structure.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "json_data": {
                    "type": "string",
                    "description": "A JSON string representing a Knowledge Structure.",
                },
                "operations": {
                    "type": "string",
                    "description": "A JSON string with an array of operation objects.",
                },
            },
            "required": ["json_data", "operations"],
        },
    },
    "derive_knowledge": {
        "name": "derive_knowledge",
        "description": "Derive a new Knowledge Object from existing premises.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "json_data": {
                    "type": "string",
                    "description": "A JSON string representing a Knowledge Structure.",
                },
                "premises": {
                    "type": "string",
                    "description": "A JSON array of canonical identities used as premises.",
                },
                "rule": {
                    "type": "string",
                    "description": "The canonical inference rule identifier.",
                },
                "conclusion_id": {
                    "type": "string",
                    "description": "Canonical identity for the new Knowledge Object.",
                },
                "conclusion_type": {
                    "type": "string",
                    "description": "Canonical type for the new Knowledge Object.",
                },
                "conclusion_name": {
                    "type": "string",
                    "description": "Human-readable name for the new Knowledge Object.",
                },
            },
            "required": ["json_data", "premises", "rule", "conclusion_id", "conclusion_type", "conclusion_name"],
        },
    },
}

# Mapping from tool name to callable
HANDLERS: Dict[str, Callable[..., str]] = {
    "validate_knowledge": validate_knowledge,
    "query_relations": query_relations,
    "compare_structures": compare_structures,
    "evolve_knowledge": evolve_knowledge,
    "derive_knowledge": derive_knowledge,
}


async def handle_request(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Handle a single JSON-RPC request and return a response."""
    method = request.get("method")
    params = request.get("params", {})
    req_id = request.get("id")

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": list(TOOLS.values()),
        }
    elif method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})
        handler = HANDLERS.get(tool_name)
        if handler is None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Tool '{tool_name}' not found"},
            }
        try:
            result = handler(**tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": result,
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(exc)},
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method '{method}' not found"},
    }


async def main_loop() -> None:
    """Read JSON-RPC requests from stdin and write responses to stdout."""
    reader = asyncio.StreamReader()
    await asyncio.get_event_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader),
        sys.stdin,
    )

    writer = asyncio.StreamWriter(sys.stdout.buffer, None, None, None)

    while True:
        line = await reader.readline()
        if not line:
            break
        try:
            request = json.loads(line.decode("utf-8"))
        except json.JSONDecodeError:
            continue

        response = await handle_request(request)
        if response is not None:
            writer.write(json.dumps(response).encode("utf-8") + b"\n")
            await writer.drain()


def main() -> None:
    """Entry point for the MCP server."""
    asyncio.run(main_loop())


if __name__ == "__main__":
    main()