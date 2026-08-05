"""
CKS Plugin Framework — abstract base class and plugin registry.

A plugin is an optional piece of functionality that:
  * checks whether its dependencies are available via ``is_available()``;
  * initialises itself through ``setup(runtime, config)``, returning a handle;
  * cleanly shuts down through ``teardown(handle)``.

``PluginRegistry`` holds the registered plugins and manages their
lifecycle (``setup_all`` / ``teardown_all``).

Adding a new plugin:
  1. Create a class ``MyPlugin(CksPlugin)`` in ``cks_mcp/plugins/``.
  2. Register it in ``server.py``: ``registry.register(MyPlugin())``.
  No changes to cks-runtime or cks-core are needed.
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from typing import Any

from cks_runtime.config import RuntimeConfig
from cks_runtime.runtime import Runtime

__all__ = ["CksPlugin", "PluginRegistry"]


class CksPlugin(ABC):
    """Abstract base class for cks-mcp plugins."""

    #: Unique machine-readable name of the plugin (snake_case).
    name: str

    #: Human-readable description.
    description: str

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check whether the plugin's required dependencies are installed.

        Must not raise exceptions — only return ``True`` or ``False``.
        """

    @abstractmethod
    def setup(self, runtime: Runtime, config: RuntimeConfig) -> Any:
        """
        Initialise the plugin.

        Called only when ``is_available()`` returned ``True``.
        Returns a handle (any object) that is passed to ``teardown``.
        May return ``None`` if the plugin decides not to start
        (e.g. because of an env flag like ``CKS_GOSSIP_ENABLED``).
        """

    @abstractmethod
    def teardown(self, handle: Any) -> None:
        """
        Cleanly shut down the plugin.

        ``handle`` is the value previously returned by ``setup``.
        If ``handle`` is ``None``, the plugin was not started; the
        implementation should handle this gracefully and do nothing.
        """


class PluginRegistry:
    """
    Registry of cks-mcp plugins.

    Lifecycle::

        registry = PluginRegistry()
        registry.register(FastEmbedPlugin())
        registry.register(GossipPlugin())

        # at startup
        handles = await registry.setup_all(runtime, config)

        # at shutdown
        await registry.teardown_all(handles)
    """

    def __init__(self) -> None:
        self._plugins: dict[str, CksPlugin] = {}

    def register(self, plugin: CksPlugin) -> None:
        """Add a plugin to the registry."""
        self._plugins[plugin.name] = plugin

    def list_all(self) -> list[dict[str, Any]]:
        """
        Return information about every registered plugin.

        Each element: ``{"name": ..., "description": ..., "available": bool}``.
        """
        return [
            {
                "name": p.name,
                "description": p.description,
                "available": p.is_available(),
            }
            for p in self._plugins.values()
        ]

    def list_available(self) -> list[str]:
        """Return the names of plugins for which ``is_available()`` is True."""
        return [p.name for p in self._plugins.values() if p.is_available()]

    def setup_all(self, runtime: Runtime, config: RuntimeConfig) -> dict[str, Any]:
        """
        Initialise every available plugin.

        Returns a ``{name: handle}`` dict for every plugin whose
        ``is_available()`` returned True (handle may be ``None`` if the
        plugin decided not to start).
        """
        handles: dict[str, Any] = {}
        for plugin in self._plugins.values():
            if not plugin.is_available():
                continue
            try:
                handle = plugin.setup(runtime, config)
                handles[plugin.name] = handle
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[CKS-MCP] ERROR: Plugin '{plugin.name}' failed to set up: {exc}",
                    file=sys.stderr,
                )
        return handles

    def teardown_all(self, handles: dict[str, Any]) -> None:
        """Tear down every plugin that has a handle."""
        for name, handle in handles.items():
            plugin = self._plugins.get(name)
            if plugin is None:
                continue
            try:
                plugin.teardown(handle)
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[CKS-MCP] ERROR: Plugin '{name}' failed to tear down: {exc}",
                    file=sys.stderr,
                )