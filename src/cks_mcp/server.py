"""
CKS MCP Server – Model Context Protocol over stdio.

A lightweight MCP server that exposes canonical CKS operations
(validate, serialize, explain, evolve, verify_source) to LLMs
via the Model Context Protocol.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from cks_runtime.runtime import Runtime
from cks_runtime_plugins.cks_core import CksCoreAdapter

from cks_mcp.tools import (
    validate_knowledge,
    serialize_knowledge,
    explain_knowledge,
    evolve_knowledge,
)
from cks_mcp.tools.verify_source import verify_source
from cks_mcp.errors import invalid_json_error, validation_failed

# ---------------------------------------------------------------------------
# Server metadata
# ---------------------------------------------------------------------------

SERVER_NAME = "cks-mcp"
SERVER_VERSION = "0.6.1"
PROTOCOL_VERSION = "2024-11-05"  # latest MCP protocol version

# ---------------------------------------------------------------------------
# Shared parameter descriptions
# ---------------------------------------------------------------------------

JSON_DATA_DESCRIPTION = (
    "A valid CKS Knowledge Structure as a JSON string. Each object has "
    "an 'identity' ({'id', 'type', 'name'}) and a free-form 'structure' "
    "dict. Relations are objects whose 'structure' contains "
    "'participants' (a list of object ids) and 'relation_type'. Example: "
    '\'{"objects": [{"identity": {"id": "obj-1", "type": "Definition", '
    '"name": "Photosynthesis"}, "structure": {"content": "..."}}, '
    '{"identity": {"id": "rel-1", "type": "Relation", "name": "r"}, '
    '"structure": {"participants": ["obj-1", "obj-2"], "relation_type": '
    '"derives"}}]}\'.'
)

TOOLS = {
    "validate_knowledge": {
        "name": "validate_knowledge",
        "description": (
            "Validate a Canonical Knowledge Structure. Returns validation result and diagnostics. "
            "Optionally accepts 'extensions' to opt into additional, non-default validation rules "
            "for this call only (see 'extensions' parameter)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "json_data": {
                    "type": "string",
                    "description": JSON_DATA_DESCRIPTION,
                },
                "extensions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional list of opt-in validation extensions to apply for this call "
                        "only (does not affect other calls). Currently available: "
                        "'embedding_projection' and 'verification_record'. "
                        "Example of a correct EmbeddingProjection with its 'represents' relation: "
                        '{"objects": ['
                        '{"identity": {"id": "src-1", "type": "Document", "name": "Real paper"}, "structure": {}}, '
                        '{"identity": {"id": "proj-1", "type": "EmbeddingProjection", "name": "projection"}, "structure": {"store_ref": "vecdb://xyz"}}, '
                        '{"identity": {"id": "rel-1", "type": "Relation", "name": "r"}, "structure": {"participants": ["src-1", "proj-1"], "relation_type": "represents"}}'
                        ']}.'
                    ),
                },
            },
            "required": ["json_data"],
        },
        "handler": validate_knowledge,
    },
    "serialize_knowledge": {
        "name": "serialize_knowledge",
        "description": "Serialize a Knowledge Structure into its canonical JSON representation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "json_data": {
                    "type": "string",
                    "description": JSON_DATA_DESCRIPTION,
                },
            },
            "required": ["json_data"],
        },
        "handler": serialize_knowledge,
    },
    "explain_knowledge": {
        "name": "explain_knowledge",
        "description": "Produce a human-readable explanation of a Knowledge Structure.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "json_data": {
                    "type": "string",
                    "description": JSON_DATA_DESCRIPTION,
                },
            },
            "required": ["json_data"],
        },
        "handler": explain_knowledge,
    },
    "evolve_knowledge": {
        "name": "evolve_knowledge",
        "description": "Apply structural evolution operators to a Knowledge Structure.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "json_data": {
                    "type": "string",
                    "description": JSON_DATA_DESCRIPTION,
                },
                "operations": {
                    "type": "array",
                    "description": (
                        "List of evolution operators to apply, in order. Each operator is an "
                        "object with a 'type' of 'add_object' | 'add_relation' | 'remove_object' "
                        "| 'remove_relation'. Example: "
                        '\'[{"type": "add_object", "identity": {"id": "obj-2", "type": "Lemma", '
                        '"name": "New"}, "structure": {}}, {"type": "add_relation", "identity": '
                        '{"id": "rel-1", "type": "Relation", "name": "r"}, "participants": '
                        '["obj-1", "obj-2"], "relation_type": "derives"}]\'.'
                    ),
                },
            },
            "required": ["json_data"],
        },
        "handler": evolve_knowledge,
    },
    "verify_source": {
        "name": "verify_source",
        "description": "Verify an external source by performing a real HTTP request. Creates a VerificationRecord that can be validated.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL of the source to verify."
                },
                "subject_id": {
                    "type": "string",
                    "description": "The ID of the Knowledge Object that this verification is about."
                }
            },
            "required": ["url", "subject_id"]
        },
        "handler": verify_source,
    },
}

# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

def _make_response(request_id: Any, result: Any = None, error: dict | None = None) -> dict[str, Any]:
    """Wrap result/error into a JSON-RPC 2.0 response."""
    resp: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if result is not None:
        resp["result"] = result
    if error is not None:
        resp["error"] = error
    return resp


def handle_request(
    runtime: Runtime,
    request: dict[str, Any],
) -> dict[str, Any]:
    """Handle a single JSON-RPC request."""
    req_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params", {})

    if method == "initialize":
        return _make_response(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
            "capabilities": {
                "tools": {},
            },
        })

    if method == "notifications/initialized":
        return {}

    if method == "ping":
        return _make_response(req_id, {})

    if method == "tools/list":
        return _make_response(req_id, {
            "tools": [
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "inputSchema": tool["inputSchema"],
                }
                for tool in TOOLS.values()
            ],
        })

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        tool = TOOLS.get(tool_name)

        if tool is None:
            return _make_response(req_id, error={
                "code": -32601,
                "message": f"Unknown tool: {tool_name}",
            })

        handler = tool["handler"]
        try:
            result = handler(runtime, arguments)
            return _make_response(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]
            })
        except Exception as e:
            return _make_response(req_id, error={
                "code": -32000,
                "message": validation_failed(str(e))["message"]
            })

    return _make_response(req_id, error={
        "code": -32601,
        "message": f"Method not found: {method}",
    })


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point for the MCP server."""
    runtime = Runtime(core=CksCoreAdapter())

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": "Parse error"},
                "id": None,
            }) + "\n")
            sys.stdout.flush()
            continue

        if isinstance(raw, list):
            responses = []
            for req in raw:
                resp = handle_request(runtime, req)
                if resp:
                    responses.append(resp)
            if responses:
                sys.stdout.write(json.dumps(responses) + "\n")
        else:
            resp = handle_request(runtime, raw)
            if resp:
                sys.stdout.write(json.dumps(resp) + "\n")

        sys.stdout.flush()


if __name__ == "__main__":
    main()