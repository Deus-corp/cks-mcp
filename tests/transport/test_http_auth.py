"""
Tests for optional HTTP token auth (``CKS_MCP_HTTP_TOKEN``) on the
HTTP transport's ``/mcp`` and ``/events`` routes.

Builds a minimal aiohttp app wired the same way ``server.main()``
wires the real one (auth middleware + ``/mcp`` + SSE routes), and
drives it with ``aiohttp.test_utils``.
"""

from __future__ import annotations

import importlib

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from cks_runtime.adapters.cks_core import CksCoreAdapter
from cks_runtime.runtime import Runtime
from cks_runtime.storage.memory_storage import InMemoryStorage

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def runtime():
    rt = await Runtime.create(core=CksCoreAdapter(), storage=InMemoryStorage())
    try:
        yield rt
    finally:
        await rt.aclose()


def _reload_auth_module():
    """
    http_auth caches CKS_MCP_HTTP_TOKEN at import time, so tests that
    change the env var via monkeypatch need to reload the module (and
    the modules that imported the cached functions from it) to pick up
    the new value.
    """
    import cks_mcp.transport.http_auth as http_auth_module

    importlib.reload(http_auth_module)

    import cks_mcp.server as server_module
    import cks_mcp.transport.http_events as http_events_module

    importlib.reload(http_events_module)
    importlib.reload(server_module)
    return server_module, http_events_module


async def _make_client(runtime, server_module, http_events_module):
    app = web.Application(middlewares=[server_module._auth_middleware])
    app["runtime"] = runtime
    app.router.add_post("/mcp", server_module._http_handler)
    broadcaster = http_events_module.register_sse_routes(app, runtime)
    test_client = TestClient(TestServer(app))
    await test_client.start_server()
    return test_client, broadcaster


async def _close_client(test_client, broadcaster):
    broadcaster.stop()
    await test_client.close()


PING_BODY = {"jsonrpc": "2.0", "id": 1, "method": "ping"}


@pytest.fixture(autouse=True)
def _reset_auth_module_after_test():
    """
    http_auth caches CKS_MCP_HTTP_TOKEN at import time, and tests here
    reload it via monkeypatch + _reload_auth_module() to exercise both
    the enabled and disabled states. monkeypatch restores the env var
    after each test, but the reloaded module's module-level cache
    would otherwise keep whatever value was live during the test and
    leak into later tests (in this file or others) that import
    ``cks_mcp.transport.http_auth`` expecting the real environment. Reload once
    more after each test, once the env var is back to its original
    state, so the cache never outlives the test that set it.
    """
    yield
    _reload_auth_module()


# ---------------------------------------------------------------------------
# Auth disabled (default / no token configured)
# ---------------------------------------------------------------------------


async def test_no_token_configured_mcp_works_unauthenticated(runtime, monkeypatch):
    monkeypatch.delenv("CKS_MCP_HTTP_TOKEN", raising=False)
    server_module, http_events_module = _reload_auth_module()

    client, broadcaster = await _make_client(runtime, server_module, http_events_module)
    try:
        response = await client.post("/mcp", json=PING_BODY)
        assert response.status == 200
    finally:
        await _close_client(client, broadcaster)


async def test_no_token_configured_events_works_unauthenticated(runtime, monkeypatch):
    monkeypatch.delenv("CKS_MCP_HTTP_TOKEN", raising=False)
    server_module, http_events_module = _reload_auth_module()

    client, broadcaster = await _make_client(runtime, server_module, http_events_module)
    try:
        response = await client.get("/events")
        assert response.status == 200
        response.close()
    finally:
        await _close_client(client, broadcaster)


# ---------------------------------------------------------------------------
# Auth enabled
# ---------------------------------------------------------------------------


async def test_events_valid_bearer_header_allowed(runtime, monkeypatch):
    monkeypatch.setenv("CKS_MCP_HTTP_TOKEN", "s3cr3t")
    server_module, http_events_module = _reload_auth_module()

    client, broadcaster = await _make_client(runtime, server_module, http_events_module)
    try:
        response = await client.get(
            "/events", headers={"Authorization": "Bearer s3cr3t"}
        )
        assert response.status == 200
        response.close()
    finally:
        await _close_client(client, broadcaster)


async def test_events_valid_query_token_allowed(runtime, monkeypatch):
    monkeypatch.setenv("CKS_MCP_HTTP_TOKEN", "s3cr3t")
    server_module, http_events_module = _reload_auth_module()

    client, broadcaster = await _make_client(runtime, server_module, http_events_module)
    try:
        response = await client.get("/events", params={"token": "s3cr3t"})
        assert response.status == 200
        response.close()
    finally:
        await _close_client(client, broadcaster)


async def test_events_missing_token_rejected(runtime, monkeypatch):
    monkeypatch.setenv("CKS_MCP_HTTP_TOKEN", "s3cr3t")
    server_module, http_events_module = _reload_auth_module()

    client, broadcaster = await _make_client(runtime, server_module, http_events_module)
    try:
        response = await client.get("/events")
        assert response.status == 401
    finally:
        await _close_client(client, broadcaster)


async def test_events_invalid_token_rejected(runtime, monkeypatch):
    monkeypatch.setenv("CKS_MCP_HTTP_TOKEN", "s3cr3t")
    server_module, http_events_module = _reload_auth_module()

    client, broadcaster = await _make_client(runtime, server_module, http_events_module)
    try:
        response = await client.get(
            "/events", headers={"Authorization": "Bearer wrong"}
        )
        assert response.status == 401
    finally:
        await _close_client(client, broadcaster)


async def test_mcp_valid_bearer_header_allowed(runtime, monkeypatch):
    monkeypatch.setenv("CKS_MCP_HTTP_TOKEN", "s3cr3t")
    server_module, http_events_module = _reload_auth_module()

    client, broadcaster = await _make_client(runtime, server_module, http_events_module)
    try:
        response = await client.post(
            "/mcp", json=PING_BODY, headers={"Authorization": "Bearer s3cr3t"}
        )
        assert response.status == 200
    finally:
        await _close_client(client, broadcaster)


async def test_mcp_valid_query_token_allowed(runtime, monkeypatch):
    monkeypatch.setenv("CKS_MCP_HTTP_TOKEN", "s3cr3t")
    server_module, http_events_module = _reload_auth_module()

    client, broadcaster = await _make_client(runtime, server_module, http_events_module)
    try:
        response = await client.post(
            "/mcp", json=PING_BODY, params={"token": "s3cr3t"}
        )
        assert response.status == 200
    finally:
        await _close_client(client, broadcaster)


async def test_mcp_missing_token_rejected(runtime, monkeypatch):
    monkeypatch.setenv("CKS_MCP_HTTP_TOKEN", "s3cr3t")
    server_module, http_events_module = _reload_auth_module()

    client, broadcaster = await _make_client(runtime, server_module, http_events_module)
    try:
        response = await client.post("/mcp", json=PING_BODY)
        assert response.status == 401
    finally:
        await _close_client(client, broadcaster)


async def test_mcp_invalid_token_rejected(runtime, monkeypatch):
    monkeypatch.setenv("CKS_MCP_HTTP_TOKEN", "s3cr3t")
    server_module, http_events_module = _reload_auth_module()

    client, broadcaster = await _make_client(runtime, server_module, http_events_module)
    try:
        response = await client.post(
            "/mcp", json=PING_BODY, headers={"Authorization": "Bearer nope"}
        )
        assert response.status == 401
    finally:
        await _close_client(client, broadcaster)
