"""Unit tests for MCP server request handling."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from cks_mcp.server import handle_request

pytestmark = pytest.mark.asyncio

VALID_KNOWLEDGE_JSON = (
    '{"objects":[{"identity":{"id":"obj-1","type":"Definition","name":"Test"},"structure":{}}]}'
)


class FakeSession:
    def __init__(self):
        self.session_id = "s1"
        self.diagnostics = []


class FakeVersion:
    def __init__(self):
        self.version_id = "v1"


@pytest.fixture
def mock_runtime():
    runtime = MagicMock()
    runtime.core_bridge.validate.return_value = MagicMock(
        valid=True, diagnostics=[], metadata={}
    )
    runtime.core_bridge.serialize.return_value = '{"serialized":true}'
    runtime.core_bridge.explain.return_value = {
        "object_count": 1,
        "relation_count": 0,
        "summary": {"test": True},
    }
    runtime.core_bridge.evolve.return_value = MagicMock()
    runtime.create_session = AsyncMock(return_value=FakeSession())
    runtime.begin_transaction.return_value = MagicMock()
    runtime.commit_transaction = AsyncMock(return_value=FakeVersion())
    return runtime


async def test_initialize(mock_runtime):
    request = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    response = await handle_request(mock_runtime, request)
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 1
    assert "result" in response
    assert response["result"]["serverInfo"]["name"] == "cks-mcp"


async def test_ping(mock_runtime):
    request = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
    response = await handle_request(mock_runtime, request)
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == 2
    assert "result" in response


async def test_tools_list(mock_runtime):
    request = {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}
    response = await handle_request(mock_runtime, request)
    tools = response["result"]["tools"]
    assert len(tools) == 71
    assert any(t["name"] == "validate_knowledge" for t in tools)


async def test_tools_call_validate(mock_runtime):
    request = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "validate_knowledge",
            "arguments": {"json_data": VALID_KNOWLEDGE_JSON},
        },
    }
    response = await handle_request(mock_runtime, request)
    assert "result" in response
    content = response["result"]["content"][0]["text"]
    result = json.loads(content)
    assert result["valid"] == True
    assert result["version_id"] == "v1"


async def test_tools_call_unknown_tool(mock_runtime):
    request = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {"name": "nonexistent", "arguments": {}},
    }
    response = await handle_request(mock_runtime, request)
    assert "error" in response
    assert response["error"]["code"] == -32601


async def test_unknown_method(mock_runtime):
    request = {"jsonrpc": "2.0", "id": 6, "method": "unknown"}
    response = await handle_request(mock_runtime, request)
    assert "error" in response
    assert response["error"]["code"] == -32601


async def test_observability_decorator_does_not_break_handler():
    from cks_mcp.observability import log_tool_call

    @log_tool_call("test_tool")
    async def fake_handler(runtime, arguments):
        return {"ok": True}

    result = await fake_handler(None, {})
    assert result == {"ok": True}


async def test_setup_event_subscriptions_does_not_raise():
    from cks_runtime.runtime import Runtime
    from cks_runtime_plugins.cks_core import CksCoreAdapter

    from cks_mcp.observability import setup_event_subscriptions

    runtime = Runtime(core=CksCoreAdapter())
    setup_event_subscriptions(runtime)
    await runtime.aclose()

class TestResolveDbPath:
    """
    Regression tests for CKS_MCP_DB_PATH resolution.

    Before this, ``main()`` computed its db path purely from
    ``data_dir()`` and never looked at ``CKS_MCP_DB_PATH`` at all,
    while ``fork_resolution_agent.py``/``critic_agent.py``/
    ``enrichment_agent.py`` all read it -- so a server and a companion
    agent started with the same ``CKS_MCP_DB_PATH`` (the documented
    way to point them at a shared database) silently ended up on two
    different SQLite files.
    """

    def test_honors_explicit_ckms_mcp_db_path(self, monkeypatch, tmp_path):
        from cks_mcp.server import _resolve_db_path

        target = tmp_path / "shared" / "cks_mcp.db"
        monkeypatch.setenv("CKS_MCP_DB_PATH", str(target))

        db_dir, db_path, explicit_db_path = _resolve_db_path()

        assert db_path == str(target)
        assert db_dir == str(target.parent)
        assert explicit_db_path == str(target)

    def test_expands_user_in_explicit_path(self, monkeypatch, tmp_path):
        from cks_mcp.server import _resolve_db_path

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("CKS_MCP_DB_PATH", "~/cks_mcp.db")

        _db_dir, db_path, explicit_db_path = _resolve_db_path()

        assert db_path == str(tmp_path / "cks_mcp.db")
        assert explicit_db_path == "~/cks_mcp.db"  # raw value, pre-expansion

    def test_falls_back_to_data_dir_when_unset(self, monkeypatch, tmp_path):

        monkeypatch.delenv("CKS_MCP_DB_PATH", raising=False)
        monkeypatch.setenv("CKS_MCP_DATA_DIR", str(tmp_path))
        # cks_mcp.paths.data_dir() resolves CKS_MCP_DATA_DIR once at
        # import time, so re-resolve it fresh here rather than relying
        # on the already-imported module-level singleton.
        import importlib

        import cks_mcp.paths as paths_module

        importlib.reload(paths_module)
        import cks_mcp.server as server_module

        importlib.reload(server_module)
        try:
            db_dir, db_path, explicit_db_path = server_module._resolve_db_path()
            assert explicit_db_path is None
            assert db_path == str(tmp_path / "cks_mcp.db")
            assert db_dir == str(tmp_path)
        finally:
            # Restore both modules to their normal (unpatched) state
            # for any other test relying on them.
            monkeypatch.delenv("CKS_MCP_DATA_DIR", raising=False)
            importlib.reload(paths_module)
            importlib.reload(server_module)

    def test_matches_fork_agent_and_critic_agent_resolution_order(
        self, monkeypatch, tmp_path
    ):
        """
        The exact same CKS_MCP_DB_PATH must resolve to the exact same
        path for the main server and for each companion agent -- this
        is the actual invariant the whole fix exists to guarantee.
        """
        from cks_mcp.critic_agent import CriticAgentSettings
        from cks_mcp.fork_resolution_agent import ForkResolutionAgentSettings
        from cks_mcp.server import _resolve_db_path

        target = tmp_path / "shared.db"
        monkeypatch.setenv("CKS_MCP_DB_PATH", str(target))

        _, server_db_path, _ = _resolve_db_path()
        fork_agent_path = ForkResolutionAgentSettings.from_env().storage_path
        critic_agent_path = CriticAgentSettings.from_env().storage_path

        assert server_db_path == str(target)
        assert fork_agent_path == str(target)
        assert critic_agent_path == str(target)