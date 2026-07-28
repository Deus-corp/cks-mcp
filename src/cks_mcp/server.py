"""
CKS MCP Server – Model Context Protocol over stdio.

A lightweight MCP server that exposes canonical CKS operations
(validate, serialize, explain, evolve, verify_source) to LLMs
via the Model Context Protocol.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Any

from cks_runtime.config import RuntimeConfig
from cks_runtime.embedding.client import HuggingFaceEmbeddingClient
from cks_runtime.runtime import Runtime
from cks_runtime.storage.memory_storage import InMemoryStorage
from cks_runtime_plugins.cks_core import CksCoreAdapter

from cks_mcp.observability import setup_event_subscriptions
from cks_mcp.paths import data_dir
from cks_mcp.prompts import PROMPTS, get_prompt, list_prompts
from cks_mcp.resources import list_resources, read_resource
from cks_mcp.tool_registry import TOOLS

# ---------------------------------------------------------------------------
# Server metadata
# ---------------------------------------------------------------------------

SERVER_NAME = "cks-mcp"
SERVER_VERSION = "1.12.1"
PROTOCOL_VERSION = "2025-11-25"  # latest stable MCP protocol version

# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------


def _make_response(
    request_id: Any, result: Any = None, error: dict | None = None
) -> dict[str, Any]:
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
        return _make_response(
            req_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
                "capabilities": {
                    "tools": {},
                    "resources": {},
                    "prompts": {},
                },
            },
        )

    if method == "notifications/initialized":
        return {}

    if method == "ping":
        return _make_response(req_id, {})

    if method == "tools/list":
        return _make_response(
            req_id,
            {
                "tools": [
                    {
                        "name": tool["name"],
                        "description": tool["description"],
                        "inputSchema": tool["inputSchema"],
                    }
                    for tool in TOOLS.values()
                ],
            },
        )

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        tool = TOOLS.get(tool_name)

        if tool is None:
            return _make_response(
                req_id,
                error={
                    "code": -32601,
                    "message": f"Unknown tool: {tool_name}",
                },
            )

        handler = tool["handler"]
        try:
            result = handler(runtime, arguments)
            return _make_response(
                req_id,
                {
                    "content": [
                        {"type": "text", "text": json.dumps(result, ensure_ascii=False)}
                    ]
                },
            )
        except Exception as e:
            error_message = str(e) if str(e) else "An internal error occurred."
            return _make_response(
                req_id,
                {
                    "content": [{"type": "text", "text": f"Error: {error_message}"}],
                    "isError": True,
                },
            )

    if method == "resources/list":
        try:
            resources = list_resources(runtime)
            return _make_response(req_id, {"resources": resources})
        except Exception as e:
            return _make_response(
                req_id,
                error={
                    "code": -32603,
                    "message": f"Failed to list resources: {e}",
                },
            )

    if method == "resources/read":
        uri = params.get("uri")
        if not uri:
            return _make_response(
                req_id,
                error={
                    "code": -32602,
                    "message": "Missing required parameter: uri",
                },
            )
        content = read_resource(runtime, uri)
        if content is None:
            return _make_response(
                req_id,
                error={
                    "code": -32602,
                    "message": f"Resource not found: {uri}",
                },
            )
        return _make_response(
            req_id,
            {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": content,
                    }
                ]
            },
        )

    if method == "prompts/list":
        try:
            prompts = list_prompts()
            return _make_response(req_id, {"prompts": prompts})
        except Exception as e:
            return _make_response(
                req_id,
                error={
                    "code": -32603,
                    "message": f"Failed to list prompts: {e}",
                },
            )

    if method == "prompts/get":
        name = params.get("name")
        if not name:
            return _make_response(
                req_id,
                error={
                    "code": -32602,
                    "message": "Missing required parameter: name",
                },
            )
        args = params.get("arguments", {})
        prompt_message = get_prompt(name, args)
        if prompt_message is None:
            return _make_response(
                req_id,
                error={
                    "code": -32602,
                    "message": f"Prompt not found: {name}",
                },
            )
        return _make_response(
            req_id,
            {
                "description": PROMPTS.get(name, {}).get("description", ""),
                "messages": prompt_message["messages"],
            },
        )

    return _make_response(
        req_id,
        error={
            "code": -32601,
            "message": f"Method not found: {method}",
        },
    )


def main() -> None:
    """Entry point for the MCP server."""
    # Determine a writable location for the SQLite database
    db_dir = str(data_dir())
    db_path = os.path.join(db_dir, "cks_mcp.db")
    storage = None
    use_persistent = True

    # Try to create the default data directory and check writability
    try:
        os.makedirs(db_dir, exist_ok=True)
        # Test write access
        test_file = os.path.join(db_dir, ".write_test")
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
    except (OSError, PermissionError) as e:
        # Default directory not writable – fall back to system temp
        use_persistent = False
        try:
            db_path = os.path.join(tempfile.gettempdir(), "cks_mcp.db")
            # Temp directory should be writable, but double-check
            with open(db_path, "a"):
                pass
            use_persistent = True
        except Exception as e2:
            # Even temp directory failed; use in-memory storage
            storage = InMemoryStorage()
            print(
                f"[CKS-MCP] WARNING: Could not open writable database file: {e} / {e2}. "
                "Using in-memory storage.",
                file=sys.stderr,
            )
    # Load environment from ~/.cks-mcp/.env if it exists
    env_file = data_dir() / ".env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())

    # Initialize embedding client (fallback to None if OpenAI unavailable)
    try:
        embedding_client = HuggingFaceEmbeddingClient()
    except Exception:
        embedding_client = None

    if storage is None and use_persistent:
        try:
            config = RuntimeConfig(storage_path=db_path)
            runtime = Runtime(
                core=CksCoreAdapter(), config=config, embedding_client=embedding_client
            )
        except Exception as e:
            print(
                f"[CKS-MCP] ERROR: Failed to initialize persistent storage: {e}. "
                "Falling back to in-memory storage.",
                file=sys.stderr,
            )
            storage = InMemoryStorage()
            runtime = Runtime(
                core=CksCoreAdapter(),
                storage=storage,
                embedding_client=embedding_client,
            )
    elif storage is not None:
        runtime = Runtime(
            core=CksCoreAdapter(), storage=storage, embedding_client=embedding_client
        )
    else:
        # use_persistent is False but storage is still None (shouldn't happen)
        storage = InMemoryStorage()
        runtime = Runtime(
            core=CksCoreAdapter(), storage=storage, embedding_client=embedding_client
        )

    setup_event_subscriptions(runtime)

    while True:
        line = sys.stdin.readline()
        if not line:
            return  # EOF

        line_stripped = line.strip()
        if line_stripped.lower().startswith("content-length:"):
            try:
                content_length = int(line_stripped.split(":")[1].strip())
            except (ValueError, IndexError):
                error_response = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "error": {"code": -32700, "message": "Parse error"},
                        "id": None,
                    }
                )
                sys.stdout.write(error_response + "\n")
                sys.stdout.flush()
                continue
            sys.stdin.readline()
            body = sys.stdin.read(content_length)
            if not body:
                return
            process_request(runtime, body, use_content_length=True)
        elif line_stripped:
            process_request(runtime, line_stripped, use_content_length=False)


def process_request(runtime: Runtime, body: str, *, use_content_length: bool) -> None:
    """Process a single JSON-RPC request body and write the response."""
    try:
        raw = json.loads(body)
    except json.JSONDecodeError:
        error_response = json.dumps(
            {
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": "Parse error"},
                "id": None,
            }
        )
        if use_content_length:
            sys.stdout.write(
                f"Content-Length: {len(error_response.encode('utf-8'))}\r\n\r\n{error_response}"
            )
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


def _send_response(
    response_obj: dict | list, *, use_content_length: bool = False
) -> None:
    """Helper to send a response, optionally with Content-Length header."""
    body = json.dumps(response_obj, ensure_ascii=False)
    if use_content_length:
        sys.stdout.write(f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n{body}")
    else:
        sys.stdout.write(body + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
