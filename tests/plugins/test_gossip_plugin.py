"""Unit tests for the GossipPlugin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cks_mcp.plugins.gossip_plugin import GossipPlugin

pytestmark = pytest.mark.asyncio


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


def test_is_available_true_when_aiohttp_present(plugin: GossipPlugin) -> None:
    with patch("importlib.import_module", return_value=MagicMock()):
        assert plugin.is_available() is True


def test_is_available_false_when_aiohttp_missing(plugin: GossipPlugin) -> None:
    with patch("importlib.import_module", side_effect=ImportError):
        assert plugin.is_available() is False


def test_is_available_does_not_raise(plugin: GossipPlugin) -> None:
    # Should never propagate an unexpected exception
    with patch("importlib.import_module", side_effect=RuntimeError("boom")):
        # must not raise
        assert plugin.is_available() is False


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------


async def test_setup_calls_setup_gossip(
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
    ):
        result = await plugin.setup(mock_runtime, mock_config)

    mock_setup_gossip.assert_called_once_with(mock_runtime, fake_settings)
    fake_handle.start.assert_awaited_once()
    assert result is fake_handle


async def test_setup_returns_none_when_gossip_disabled(
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
        result = await plugin.setup(mock_runtime, mock_config)

    assert result is None


async def test_setup_works_from_inside_a_running_event_loop(
    plugin: GossipPlugin, mock_runtime: MagicMock, mock_config: MagicMock
) -> None:
    """
    Regression test for the nested-``asyncio.run()`` bug: ``setup()``
    is always awaited by ``PluginRegistry.setup_all`` from inside
    ``server.py``'s own already-running event loop (this test itself
    runs inside pytest-asyncio's event loop, matching that). The old
    ``asyncio.run(handle.start())`` implementation raised
    ``RuntimeError: asyncio.run() cannot be called from a running
    event loop`` in exactly this situation -- silently swallowed by
    ``PluginRegistry.setup_all``'s broad ``except Exception``, so
    gossip never actually started whenever ``CKS_GOSSIP_ENABLED=true``
    was set. Calling ``await plugin.setup(...)`` directly, with no
    mocking of ``asyncio`` at all, must succeed and must actually
    ``await`` the handle's ``start()``.
    """
    fake_handle = MagicMock()
    fake_handle.start = AsyncMock()

    with (
        patch(
            "cks_mcp.plugins.gossip_plugin.GossipSettings.from_env",
            return_value=MagicMock(),
        ),
        patch(
            "cks_mcp.plugins.gossip_plugin.setup_gossip",
            return_value=fake_handle,
        ),
    ):
        result = await plugin.setup(mock_runtime, mock_config)

    assert result is fake_handle
    fake_handle.start.assert_awaited_once()


# ---------------------------------------------------------------------------
# teardown
# ---------------------------------------------------------------------------


async def test_teardown_none_handle_is_noop(plugin: GossipPlugin) -> None:
    """teardown(None) must do nothing."""
    await plugin.teardown(None)  # must not raise


async def test_teardown_stops_handle(plugin: GossipPlugin) -> None:
    """teardown(handle) awaits handle.stop() directly."""
    fake_handle = MagicMock()
    fake_handle.stop = AsyncMock()

    await plugin.teardown(fake_handle)

    fake_handle.stop.assert_awaited_once()
