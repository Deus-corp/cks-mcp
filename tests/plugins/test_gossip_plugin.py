"""Unit tests for GossipPlugin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cks_mcp.plugins.gossip_plugin import GossipPlugin


@pytest.fixture
def plugin() -> GossipPlugin:
    return GossipPlugin()


@pytest.fixture
def mock_runtime() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_config() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


def test_is_available_true_when_aiohttp_installed(plugin: GossipPlugin) -> None:
    """is_available() returns True when aiohttp is importable."""
    with patch("importlib.import_module", return_value=MagicMock()):
        assert plugin.is_available() is True


def test_is_available_false_when_aiohttp_missing(plugin: GossipPlugin) -> None:
    """is_available() returns False when aiohttp is not installed."""
    with patch("importlib.import_module", side_effect=ImportError):
        assert plugin.is_available() is False


def test_is_available_does_not_raise(plugin: GossipPlugin) -> None:
    """is_available() must never propagate an exception."""
    with patch("importlib.import_module", side_effect=ImportError("no aiohttp")):
        result = plugin.is_available()
    assert result is False


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------


def test_setup_calls_setup_gossip(
    plugin: GossipPlugin, mock_runtime: MagicMock, mock_config: MagicMock
) -> None:
    """setup() delegates to setup_gossip and starts the handle."""
    fake_handle = MagicMock()
    fake_handle.start = AsyncMock()

    fake_settings = MagicMock()

    with (
        patch(
            "cks_mcp.plugins.gossip_plugin.GossipSettings.from_env",
            return_value=fake_settings,
        ),
        patch(
            "cks_mcp.plugins.gossip_plugin.setup_gossip",
            return_value=fake_handle,
        ) as mock_setup_gossip,
        patch("asyncio.run") as mock_asyncio_run,
    ):
        plugin.setup(mock_runtime, mock_config)

    mock_setup_gossip.assert_called_once_with(mock_runtime, fake_settings)
    mock_asyncio_run.assert_called_once()
    # asyncio.run was called with fake_handle.start() — the coroutine
    # object isn't easily compared, but we can verify it was called once


def test_setup_returns_none_when_gossip_disabled(
    plugin: GossipPlugin, mock_runtime: MagicMock, mock_config: MagicMock
) -> None:
    """setup() propagates None when setup_gossip returns None (gossip disabled)."""
    with (
        patch(
            "cks_mcp.plugins.gossip_plugin.GossipSettings.from_env",
            return_value=MagicMock(),
        ),
        patch("cks_mcp.plugins.gossip_plugin.setup_gossip", return_value=None),
    ):
        result = plugin.setup(mock_runtime, mock_config)

    assert result is None


# ---------------------------------------------------------------------------
# teardown
# ---------------------------------------------------------------------------


def test_teardown_none_handle_is_noop(plugin: GossipPlugin) -> None:
    """teardown(None) must do nothing."""
    plugin.teardown(None)  # must not raise


def test_teardown_stops_handle(plugin: GossipPlugin) -> None:
    """teardown(handle) calls handle.stop() via asyncio.run."""
    fake_handle = MagicMock()
    fake_handle.stop = AsyncMock()

    with patch("asyncio.run") as mock_asyncio_run:
        plugin.teardown(fake_handle)

    mock_asyncio_run.assert_called_once()


# ---------------------------------------------------------------------------
# metadata
# ---------------------------------------------------------------------------


def test_plugin_name() -> None:
    assert GossipPlugin.name == "gossip"


def test_plugin_description_mentions_aiohttp() -> None:
    assert "aiohttp" in GossipPlugin.description.lower()