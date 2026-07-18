"""
CKS MCP Server – Model Context Protocol over stdio.

A lightweight MCP server that exposes canonical CKS operations
(validate, serialize, explain, evolve) to LLMs via the
Model Context Protocol.
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

# ---------------------------------------------------------------------------
# Server metadata
# ---------------------------------------------------------------------------

SERVER_NAME = "cks-mcp"
SERVER_VERSION = "0.2.0"
PROTOCOL_VERSION = "2024-11-05"  # latest MCP protocol version

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOLS = {
    "validate_knowledge": {
        "name": "validate_knowledge",
        "description": "Validate a Canonical Knowledge Structure. Returns validation result and diagnostics.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "json_data": {
                    "type": "string",
                    "description": "A valid CKS Knowledge Structure as a JSON string.",
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
                    "description": "A valid CKS Knowledge Structure as a JSON string.",
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
                    "description": "A valid CKS Knowledge Structure as a JSON string.",
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
                    "description": "A valid CKS Knowledge Structure as a JSON string.",
                },
                "operations": {
                    "type": "array",
                    "description": "List of evolution operators to apply.",
                },
            },
            "required": ["json_data"],
        },
        "handler": evolve_knowledge,
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

    # ------------------------------------------------------------------
    # MCP lifecycle methods
    # ------------------------------------------------------------------

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
        # No response expected for notifications
        return {}  # will be filtered out

    if method == "ping":
        return _make_response(req_id, {})

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

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

        try:
            handler = tool["handler"]
            result = handler(runtime, arguments)
            return _make_response(req_id, {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result, ensure_ascii=False),
                    }
                ]
            })
        except Exception as exc:
            return _make_response(req_id, error={
                "code": -32000,
                "message": str(exc),
            })

    # ------------------------------------------------------------------
    # Unknown method
    # ------------------------------------------------------------------

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

        # Support both single requests and batch (array)
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