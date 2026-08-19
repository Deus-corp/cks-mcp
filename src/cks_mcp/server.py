"""
CKS MCP Server – Model Context Protocol over stdio and optionally HTTP.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import os
import sys
import tempfile
from typing import Any

import aiohttp_cors
from aiohttp import web
from aiohttp.web import Request, Response
from cks_runtime.adapters.cks_core import CksCoreAdapter
from cks_runtime.config import RuntimeConfig
from cks_runtime.runtime import Runtime
from cks_runtime.storage.memory_storage import InMemoryStorage

from cks_mcp.agents.embedded_agents import start_embedded_agents, stop_embedded_agents
from cks_mcp.observability import setup_event_subscriptions
from cks_mcp.paths import data_dir
from cks_mcp.plugin import PluginRegistry
from cks_mcp.plugins import FastEmbedPlugin, GossipPlugin
from cks_mcp.prompts import PROMPTS, get_prompt, list_prompts
from cks_mcp.registry import TOOLS
from cks_mcp.resources import list_resources, read_resource
from cks_mcp.tools.list_plugins.handler import set_plugin_registry
from cks_mcp.transport.http_auth import is_request_authorized
from cks_mcp.transport.http_events import register_sse_routes

# ---------------------------------------------------------------------------
# Server metadata
# ---------------------------------------------------------------------------

def _server_version() -> str:
    try:
        return importlib.metadata.version("cks-mcp")
    except importlib.metadata.PackageNotFoundError:
        from ._version import __version__
        return __version__

SERVER_NAME = "cks-mcp"
SERVER_VERSION = _server_version()
PROTOCOL_VERSION = "2025-11-25"

# ---------------------------------------------------------------------------
# Request handler
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
        content = await read_resource(runtime, uri)
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


async def _http_handler(request: Request) -> Response:
    """Handle incoming JSON-RPC request over HTTP."""
    try:
        body = await request.text()
    except Exception:
        return web.json_response(
            {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None},
            status=400,
        )

    runtime = request.app['runtime']
    try:
        raw = json.loads(body)
    except json.JSONDecodeError:
        return web.json_response(
            {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None},
            status=400,
        )

    if isinstance(raw, list):
        responses = []
        for req in raw:
            resp = await handle_request(runtime, req)
            if resp:
                responses.append(resp)
        if responses:
            return web.json_response(responses)
        return web.json_response({})
    else:
        resp = await handle_request(runtime, raw)
        if resp:
            return web.json_response(resp)
        return web.json_response({})


@web.middleware
async def _auth_middleware(request: Request, handler):
    """
    Enforce ``CKS_MCP_HTTP_TOKEN`` (if set) on the HTTP transport's
    routes (``/mcp`` and ``/events*``). No-op if the token is unset,
    preserving the historical no-auth behavior. Only ever installed on
    the HTTP transport's aiohttp app -- stdio transport has no
    ``web.Application`` and is unaffected.
    """
    if not is_request_authorized(request):
        return web.json_response(
            {"error": "Unauthorized"},
            status=401,
        )
    return await handler(request)


def _resolve_db_path() -> tuple[str, str, str | None]:
    explicit_db_path = os.environ.get("CKS_MCP_DB_PATH")
    if explicit_db_path:
        db_path = os.path.expanduser(explicit_db_path)
        db_dir = os.path.dirname(db_path) or "."
    else:
        db_dir = str(data_dir())
        db_path = os.path.join(db_dir, "cks_mcp.db")
    return db_dir, db_path, explicit_db_path


async def main() -> None:
    db_dir, db_path, explicit_db_path = _resolve_db_path()
    http_port_str = os.environ.get("CKS_MCP_HTTP_PORT", "")
    http_port: int | None = None
    if http_port_str:
        try:
            http_port = int(http_port_str)
        except ValueError:
            print(
                f"[CKS-MCP] WARNING: Invalid CKS_MCP_HTTP_PORT={http_port_str!r}, ignoring HTTP server.",
                file=sys.stderr,
            )

    storage = None
    use_persistent = True

    try:
        await asyncio.to_thread(os.makedirs, db_dir, exist_ok=True)
        test_file = os.path.join(db_dir, f".write_test_{os.getpid()}")
        async def _write_test():
            def _write():
                with open(test_file, "w") as f:
                    f.write("test")
            await asyncio.to_thread(_write)
        await _write_test()
        await asyncio.to_thread(os.remove, test_file)
    except (OSError, PermissionError):
        use_persistent = False
        if explicit_db_path:
            print(
                f"[CKS-MCP] WARNING: CKS_MCP_DB_PATH={explicit_db_path!r} is not "
                "writable; falling back to a temporary database. Any companion "
                "agent process (cks-fork-agent, cks-critic-agent, "
                "cks-enrichment-agent) configured with the same CKS_MCP_DB_PATH "
                "will not see this server's data until the path is fixed.",
                file=sys.stderr,
            )
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

    print(
        f"[CKS-MCP] Database path: {db_path!r} "
        f"({'persistent' if use_persistent else 'in-memory'}"
        + (
            f", from CKS_MCP_DB_PATH={explicit_db_path!r}"
            if explicit_db_path and use_persistent
            else ""
        )
        + ")",
        file=sys.stderr,
    )

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

    registry = PluginRegistry()
    registry.register(FastEmbedPlugin())
    registry.register(GossipPlugin())
    set_plugin_registry(registry)

    available = registry.list_available()
    print(
        f"[CKS-MCP] Available plugins: {available if available else '(none)'}",
        file=sys.stderr,
    )

    if storage is None and use_persistent:
        try:
            config = RuntimeConfig(storage_path=db_path)
            runtime = await Runtime.create(
                core=CksCoreAdapter(), config=config
            )
        except Exception as e:
            print(
                f"[CKS-MCP] ERROR: Failed to initialize persistent storage: {e}. "
                "Falling back to in-memory storage.",
                file=sys.stderr,
            )
            storage = InMemoryStorage()
            config = RuntimeConfig()
            runtime = await Runtime.create(
                core=CksCoreAdapter(),
                storage=storage,
            )
    else:
        config = RuntimeConfig()
        runtime = await Runtime.create(
            core=CksCoreAdapter(), storage=storage
        )

    setup_event_subscriptions(runtime)

    plugin_handles = await registry.setup_all(runtime, config)

    # --- Embedded agents (ADR-012, opt-in via CKS_EMBEDDED_AGENTS / CKS_EMBED_*)
    # Only meaningful with a real persistent database file that a
    # separately-constructed Runtime can also open -- an in-memory
    # storage fallback has nothing for a second Runtime to share.
    embedded_agent_handles: list[Any] = []
    if storage is None and use_persistent:
        embedded_agent_handles = start_embedded_agents(db_path)

    # --- HTTP transport (optional) ---
    http_runner = None
    sse_broadcaster = None
    if http_port is not None:
        try:
            app = web.Application(middlewares=[_auth_middleware])
            app['runtime'] = runtime
            app.router.add_post('/mcp', _http_handler)
            # Real-time session event streaming (SSE) -- see transport/http_events.py
            # and transport/sse.py. Only available when the HTTP transport itself is
            # enabled; there is no stdio equivalent.
            sse_broadcaster = register_sse_routes(app, runtime)

            # CORS: разрешаем все источники для локальной разработки
            cors = aiohttp_cors.setup(app, defaults={
                "*": aiohttp_cors.ResourceOptions(
                    allow_credentials=False,
                    expose_headers="*",
                    allow_headers="*",
                )
            })
            for route in list(app.router.routes()):
                cors.add(route)

            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '127.0.0.1', http_port)
            await site.start()
            http_runner = runner
            print(f"[CKS-MCP] HTTP server listening on 127.0.0.1:{http_port}", file=sys.stderr)
        except Exception as e:
            print(f"[CKS-MCP] ERROR: Failed to start HTTP server: {e}", file=sys.stderr)

    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    try:
        while True:
            line = await reader.readline()
            if not line:
                break

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

                while True:
                    header_line = (await reader.readline()).decode().strip()
                    if not header_line:
                        break
                    if header_line.lower().startswith("content-length:"):
                        content_length = int(header_line.split(":")[1].strip())

                try:
                    body = await reader.readexactly(content_length)
                except asyncio.IncompleteReadError as e:
                    body = e.partial
                if not body:
                    break
                await process_request(runtime, body.decode(), use_content_length=True)
            elif line_stripped:
                await process_request(runtime, line_stripped, use_content_length=False)
    finally:
        if http_runner:
            await http_runner.cleanup()
        if sse_broadcaster:
            sse_broadcaster.stop()
        await stop_embedded_agents(embedded_agent_handles)
        await registry.teardown_all(plugin_handles)
        await runtime.aclose()


def main_sync() -> None:
    asyncio.run(main())


async def process_request(runtime: Runtime, body: str, *, use_content_length: bool) -> None:
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
    body = json.dumps(response_obj, ensure_ascii=False)
    if use_content_length:
        sys.stdout.write(f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n{body}")
    else:
        sys.stdout.write(body + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    asyncio.run(main())