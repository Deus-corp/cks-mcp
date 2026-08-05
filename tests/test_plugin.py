"""Unit tests for CksPlugin / PluginRegistry."""

from __future__ import annotations

from unittest.mock import MagicMock

from cks_mcp.plugin import CksPlugin, PluginRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _AlwaysAvailable(CksPlugin):
    name = "always"
    description = "Always available test plugin."

    def is_available(self) -> bool:
        return True

    def setup(self, runtime, config):  # type: ignore[override]
        return "handle-always"

    def teardown(self, handle) -> None:  # type: ignore[override]
        pass


class _NeverAvailable(CksPlugin):
    name = "never"
    description = "Never available test plugin."

    def is_available(self) -> bool:
        return False

    def setup(self, runtime, config):  # type: ignore[override]  # pragma: no cover
        return "handle-never"

    def teardown(self, handle) -> None:  # type: ignore[override]  # pragma: no cover
        pass


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


def test_register_adds_plugin() -> None:
    registry = PluginRegistry()
    plugin = _AlwaysAvailable()
    registry.register(plugin)
    names = [p["name"] for p in registry.list_all()]
    assert "always" in names


def test_register_overwrites_same_name() -> None:
    registry = PluginRegistry()
    registry.register(_AlwaysAvailable())
    registry.register(_AlwaysAvailable())  # second registration
    assert len(registry.list_all()) == 1


# ---------------------------------------------------------------------------
# list_available
# ---------------------------------------------------------------------------


def test_list_available_filters_unavailable() -> None:
    registry = PluginRegistry()
    registry.register(_AlwaysAvailable())
    registry.register(_NeverAvailable())
    available = registry.list_available()
    assert available == ["always"]


def test_list_available_empty_when_none_available() -> None:
    registry = PluginRegistry()
    registry.register(_NeverAvailable())
    assert registry.list_available() == []


# ---------------------------------------------------------------------------
# list_all
# ---------------------------------------------------------------------------


def test_list_all_includes_availability_flag() -> None:
    registry = PluginRegistry()
    registry.register(_AlwaysAvailable())
    registry.register(_NeverAvailable())
    info = {p["name"]: p for p in registry.list_all()}
    assert info["always"]["available"] is True
    assert info["never"]["available"] is False


# ---------------------------------------------------------------------------
# setup_all
# ---------------------------------------------------------------------------


def test_setup_all_calls_setup_for_available_plugins() -> None:
    registry = PluginRegistry()
    plugin = MagicMock(spec=CksPlugin)
    plugin.name = "mock_plugin"
    plugin.is_available.return_value = True
    plugin.setup.return_value = "mock-handle"
    registry.register(plugin)

    runtime = MagicMock()
    config = MagicMock()
    handles = registry.setup_all(runtime, config)

    plugin.setup.assert_called_once_with(runtime, config)
    assert handles == {"mock_plugin": "mock-handle"}


def test_setup_all_skips_unavailable_plugins() -> None:
    registry = PluginRegistry()
    plugin = MagicMock(spec=CksPlugin)
    plugin.name = "skip_me"
    plugin.is_available.return_value = False
    registry.register(plugin)

    handles = registry.setup_all(MagicMock(), MagicMock())

    plugin.setup.assert_not_called()
    assert handles == {}


def test_setup_all_logs_error_and_continues_on_exception(capsys) -> None:
    registry = PluginRegistry()

    failing = MagicMock(spec=CksPlugin)
    failing.name = "failing"
    failing.is_available.return_value = True
    failing.setup.side_effect = RuntimeError("boom")

    fine = MagicMock(spec=CksPlugin)
    fine.name = "fine"
    fine.is_available.return_value = True
    fine.setup.return_value = "ok"

    registry.register(failing)
    registry.register(fine)

    handles = registry.setup_all(MagicMock(), MagicMock())

    assert "failing" not in handles
    assert handles.get("fine") == "ok"
    captured = capsys.readouterr()
    assert "failing" in captured.err


# ---------------------------------------------------------------------------
# teardown_all
# ---------------------------------------------------------------------------


def test_teardown_all_calls_teardown_for_each_handle() -> None:
    registry = PluginRegistry()
    plugin = MagicMock(spec=CksPlugin)
    plugin.name = "mock_plugin"
    plugin.is_available.return_value = True
    plugin.setup.return_value = "h"
    registry.register(plugin)

    handles = {"mock_plugin": "h"}
    registry.teardown_all(handles)

    plugin.teardown.assert_called_once_with("h")


def test_teardown_all_logs_error_and_continues_on_exception(capsys) -> None:
    registry = PluginRegistry()

    failing = MagicMock(spec=CksPlugin)
    failing.name = "bad_teardown"
    failing.teardown.side_effect = RuntimeError("crash")
    registry.register(failing)

    registry.teardown_all({"bad_teardown": "some-handle"})

    captured = capsys.readouterr()
    assert "bad_teardown" in captured.err


def test_teardown_all_ignores_unknown_plugin_names() -> None:
    """teardown_all should not crash when handle name not in registry."""
    registry = PluginRegistry()
    # No crash expected — the plugin was never registered.
    registry.teardown_all({"ghost": "handle"})