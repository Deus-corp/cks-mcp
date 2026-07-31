"""
CKS MCP Server – Model Context Protocol over stdio.

A lightweight MCP server that exposes canonical CKS operations
(validate, serialize, explain, evolve, verify_source) to LLMs
via the Model Context Protocol. Now fully async.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
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
from cks_mcp.registry import TOOLS
from cks_mcp.resources import list_resources, read_resource

# ---------------------------------------------------------------------------
# Server metadata
# ---------------------------------------------------------------------------

def _server_version() -> str:
    try:
        return importlib.metadata.version("cks-mcp")
    except importlib.metadata.PackageNotFoundError:
        return "1.17.0"  # dev fallback для грядущего релиза

SERVER_NAME = "cks-mcp"
SERVER_VERSION = _server_version()
PROTOCOL_VERSION = "2025-11-25"

# ---------------------------------------------------------------------------
# Request handler (синхронный — только формирует ответ, не делает I/O)
# ---------------------------------------------------------------------------

def _make_response(
    request_id: Any, result: Any = None, error: dict | None = None
) -> dict[str, Any]:
    resp: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if result is not None:
        resp["result"] = result
    if error is not None:
        resp["error"] = error
    return resp


async def handle_request(
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
            result = await handler(runtime, arguments)
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


async def main() -> None:
    """Entry point for the MCP server. Async."""
    db_dir = str(data_dir())
    db_path = os.path.join(db_dir, "cks_mcp.db")
    storage = None
    use_persistent = True

    try:
        await asyncio.to_thread(os.makedirs, db_dir, exist_ok=True)
        test_file = os.path.join(db_dir, ".write_test")
        async def _write_test():
            def _write():
                with open(test_file, "w") as f:
                    f.write("test")
            await asyncio.to_thread(_write)
        await _write_test()
        await asyncio.to_thread(os.remove, test_file)
    except (OSError, PermissionError):
        use_persistent = False
        try:
            db_path = os.path.join(tempfile.gettempdir(), "cks_mcp.db")
            async def _touch():
                def _touch_sync():
                    with open(db_path, "a"):
                        pass
                await asyncio.to_thread(_touch_sync)
            await _touch()
            use_persistent = True
        except Exception:
            storage = InMemoryStorage()
            print(
                "[CKS-MCP] WARNING: No writable database file. Using in-memory storage.",
                file=sys.stderr,
            )

    # Загружаем переменные окружения из ~/.cks-mcp/.env
    env_file = data_dir() / ".env"
    if env_file.exists():
        def _read_env():
            return env_file.read_text()
        content = await asyncio.to_thread(_read_env)
        lines = content.splitlines()
        for line in lines:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())

    # Инициализируем embedding-клиент
    embedding_client = None
    try:
        embedding_client = HuggingFaceEmbeddingClient()
    except Exception as exc:
        print(
            f"[CKS-MCP] WARNING: Embedding client unavailable — "
            f"semantic search will not work. Cause: {exc}",
            file=sys.stderr,
        )

    # Создаём Runtime (асинхронно, с восстановлением сессий и запуском outbox-worker)
    if storage is None and use_persistent:
        try:
            config = RuntimeConfig(storage_path=db_path)
            runtime = await Runtime.create(
                core=CksCoreAdapter(), config=config, embedding_client=embedding_client
            )
        except Exception as e:
            print(
                f"[CKS-MCP] ERROR: Failed to initialize persistent storage: {e}. "
                "Falling back to in-memory storage.",
                file=sys.stderr,
            )
            storage = InMemoryStorage()
            runtime = await Runtime.create(
                core=CksCoreAdapter(),
                storage=storage,
                embedding_client=embedding_client,
            )
    else:
        runtime = await Runtime.create(
            core=CksCoreAdapter(), storage=storage, embedding_client=embedding_client
        )

    setup_event_subscriptions(runtime)

    # Неблокирующее чтение stdin через asyncio
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        line = await reader.readline()
        if not line:
            break  # EOF

        line_stripped = line.decode().strip()
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

            # Читаем заголовки до пустой строки
            while True:
                header_line = (await reader.readline()).decode().strip()
                if not header_line:
                    break
                if header_line.lower().startswith("content-length:"):
                    content_length = int(header_line.split(":")[1].strip())

            try:
                body = await reader.readexactly(content_length)
            except asyncio.IncompleteReadError as e:
                body = e.partial  # обработали частичные данные
            if not body:
                break
            await process_request(runtime, body.decode(), use_content_length=True)
        elif line_stripped:
            await process_request(runtime, line_stripped, use_content_length=False)

    await runtime.aclose()


def main_sync() -> None:
    """Синхронная точка входа для консольного скрипта."""
    asyncio.run(main())


async def process_request(runtime: Runtime, body: str, *, use_content_length: bool) -> None:
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
            resp = await handle_request(runtime, req)
            if resp:
                responses.append(resp)
        if responses:
            _send_response(responses, use_content_length=use_content_length)
    else:
        resp = await handle_request(runtime, raw)
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
    asyncio.run(main())