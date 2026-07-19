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
from cks_mcp.tools.revert import list_versions, revert_version

# ---------------------------------------------------------------------------
# Server metadata
# ---------------------------------------------------------------------------

SERVER_NAME = "cks-mcp"
SERVER_VERSION = "0.7.6"
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
            "for this call only (see 'extensions' parameter). "
            "Returns a 'session_id' that can be used with list_versions and revert_version to track and manage version history."
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
        "description": (
            "Apply structural evolution operators to a Knowledge Structure. "
            "Returns a new 'session_id' and 'version_id'. The 'session_id' can be used with list_versions and revert_version."
        ),
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
                "session_id": {
                    "type": "string",
                    "description": "Optional. The ID of an existing session to continue. If not provided, a new session is created."
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
    "list_versions": {
        "name": "list_versions",
        "description": "List all available versions of a session's history. Requires a 'session_id' obtained from a previous call to validate_knowledge or evolve_knowledge.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The ID of the session to list versions for."
                }
            },
            "required": ["session_id"]
        },
        "handler": list_versions,
    },
    "revert_version": {
        "name": "revert_version",
        "description": "Revert a session's Knowledge Structure to a specific previous version. Requires a 'session_id' obtained from a previous call to validate_knowledge or evolve_knowledge.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The ID of the session to revert."
                },
                "target_version_id": {
                    "type": "string",
                    "description": "The ID of the version to revert to."
                }
            },
            "required": ["session_id", "target_version_id"]
        },
        "handler": revert_version,
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
            # Возвращаем ошибку как часть инструментального ответа
            error_message = str(e) if str(e) else "An internal error occurred."
            return _make_response(req_id, {
                "content": [{"type": "text", "text": f"Error: {error_message}"}],
                "isError": True
            })

    return _make_response(req_id, error={
        "code": -32601,
        "message": f"Method not found: {method}",
    })


def main() -> None:
    """Entry point for the MCP server, supporting both Content-Length and line-delimited modes."""
    runtime = Runtime(core=CksCoreAdapter())

    while True:
        line = sys.stdin.readline()
        if not line:
            return  # EOF

        line_stripped = line.strip()
        if line_stripped.lower().startswith("content-length:"):
            content_length = int(line_stripped.split(":")[1].strip())
            # Read the blank line after the header
            sys.stdin.readline()
            body = sys.stdin.read(content_length)
            if not body:
                return
            process_request(runtime, body, use_content_length=True)
        elif line_stripped:
            # Line-delimited fallback (old MCP clients)
            process_request(runtime, line_stripped, use_content_length=False)


def process_request(runtime: Runtime, body: str, *, use_content_length: bool) -> None:
    """Process a single JSON-RPC request body and write the response."""
    try:
        raw = json.loads(body)
    except json.JSONDecodeError:
        error_response = json.dumps({
            "jsonrpc": "2.0",
            "error": {"code": -32700, "message": "Parse error"},
            "id": None,
        })
        if use_content_length:
            sys.stdout.write(f"Content-Length: {len(error_response.encode('utf-8'))}\r\n\r\n{error_response}")
        else:
            sys.stdout.write(error_response + "\n")
        sys.stdout.flush()
        return

    if isinstance(raw, list):
        responses = []
        for req in raw:
            resp = handle_request(runtime, req)
            if resp:
                responses.append(resp)
        if responses:
            _send_response(responses, use_content_length=use_content_length)
    else:
        resp = handle_request(runtime, raw)
        if resp:
            _send_response(resp, use_content_length=use_content_length)


def _send_response(response_obj: dict | list, *, use_content_length: bool = False) -> None:
    """Helper to send a response, optionally with Content-Length header."""
    body = json.dumps(response_obj, ensure_ascii=False)
    if use_content_length:
        sys.stdout.write(f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n{body}")
    else:
        sys.stdout.write(body + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()