"""Unit tests for the list_plugins MCP tool."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cks_mcp.tools.list_plugins.handler import list_plugins, set_plugin_registry

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_registry():
    """Isolate each test: reset the module-level registry to None."""
    set_plugin_registry(None)  # type: ignore[arg-type]
    yield
    set_plugin_registry(None)  # type: ignore[arg-type]


@pytest.fixture
def mock_runtime() -> MagicMock:
    # list_plugins never touches the runtime directly.
    return MagicMock()


# ---------------------------------------------------------------------------
# No registry injected
# ---------------------------------------------------------------------------


async def test_returns_empty_when_no_registry(mock_runtime: MagicMock) -> None:
    result = await list_plugins(mock_runtime, {})
    assert result == {"plugins": [], "available_count": 0, "total_count": 0}


# ---------------------------------------------------------------------------
# Registry injected — happy paths
# ---------------------------------------------------------------------------


def _make_registry(plugins_info: list[dict], available_names: list[str]) -> MagicMock:
    registry = MagicMock()
    registry.list_all.return_value = plugins_info
    registry.list_available.return_value = available_names
    return registry


async def test_returns_all_plugins(mock_runtime: MagicMock) -> None:
    plugins_info = [
        {"name": "fastembed", "description": "desc-a", "available": True},
        {"name": "gossip", "description": "desc-b", "available": False},
    ]
    registry = _make_registry(plugins_info, available_names=["fastembed"])
    set_plugin_registry(registry)

    result = await list_plugins(mock_runtime, {})

    assert result["total_count"] == 2
    assert result["available_count"] == 1
    assert len(result["plugins"]) == 2


async def test_available_count_matches_list_available(mock_runtime: MagicMock) -> None:
    plugins_info = [
        {"name": "a", "description": "d", "available": True},
        {"name": "b", "description": "d", "available": True},
        {"name": "c", "description": "d", "available": False},
    ]
    registry = _make_registry(plugins_info, available_names=["a", "b"])
    set_plugin_registry(registry)

    result = await list_plugins(mock_runtime, {})

    assert result["available_count"] == 2
    assert result["total_count"] == 3


async def test_plugins_list_matches_registry_list_all(mock_runtime: MagicMock) -> None:
    plugins_info = [
        {"name": "fastembed", "description": "Embedding provider", "available": True},
    ]
    registry = _make_registry(plugins_info, available_names=["fastembed"])
    set_plugin_registry(registry)

    result = await list_plugins(mock_runtime, {})

    assert result["plugins"] == plugins_info


async def test_empty_registry_returns_zeros(mock_runtime: MagicMock) -> None:
    registry = _make_registry([], available_names=[])
    set_plugin_registry(registry)

    result = await list_plugins(mock_runtime, {})

    assert result == {"plugins": [], "available_count": 0, "total_count": 0}


async def test_arguments_are_ignored(mock_runtime: MagicMock) -> None:
    """list_plugins accepts no arguments; any extras must be silently ignored."""
    registry = _make_registry([], available_names=[])
    set_plugin_registry(registry)

    result = await list_plugins(mock_runtime, {"unexpected_key": "ignored"})

    assert "plugins" in result