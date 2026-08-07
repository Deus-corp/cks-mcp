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
    async def setup(self, runtime: Runtime, config: RuntimeConfig) -> Any:
        """
        Initialise the plugin.

        Called only when ``is_available()`` returned ``True``.
        Returns a handle (any object) that is passed to ``teardown``.
        May return ``None`` if the plugin decides not to start
        (e.g. because of an env flag like ``CKS_GOSSIP_ENABLED``).

        ``async`` because plugin initialisation may itself need to
        await asynchronous work (e.g. ``GossipPlugin`` starting a
        ``GossipService``/``GossipServer``) -- see ``PluginRegistry``'s
        own docstring for why this must never reach for ``asyncio.run()``
        to bridge that: ``setup_all`` already runs inside ``server.py``'s
        ``main()`` event loop, so a plugin here is always free to
        ``await`` directly.
        """

    @abstractmethod
    async def teardown(self, handle: Any) -> None:
        """
        Cleanly shut down the plugin.

        ``handle`` is the value previously returned by ``setup``.
        If ``handle`` is ``None``, the plugin was not started; the
        implementation should handle this gracefully and do nothing.

        ``async`` for the same reason as ``setup`` above.
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

    async def setup_all(self, runtime: Runtime, config: RuntimeConfig) -> dict[str, Any]:
        """
        Initialise every available plugin.

        Returns a ``{name: handle}`` dict for every plugin whose
        ``is_available()`` returned True (handle may be ``None`` if the
        plugin decided not to start).

        Must be awaited from inside a running event loop (``server.py``'s
        ``main()`` already is one) -- this is what lets a plugin's
        ``setup()`` do genuinely async work (start a background
        service, open a network listener, ...) via a plain ``await``,
        without ever needing to spin up a *second* event loop of its
        own (``asyncio.run()`` raises ``RuntimeError`` if called from
        inside a loop that's already running -- see ``GossipPlugin``'s
        history for why that used to be a real, silently-swallowed
        failure mode here).
        """
        handles: dict[str, Any] = {}
        for plugin in self._plugins.values():
            if not plugin.is_available():
                continue
            try:
                handle = await plugin.setup(runtime, config)
                handles[plugin.name] = handle
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[CKS-MCP] ERROR: Plugin '{plugin.name}' failed to set up: {exc}",
                    file=sys.stderr,
                )
        return handles

    async def teardown_all(self, handles: dict[str, Any]) -> None:
        """Tear down every plugin that has a handle."""
        for name, handle in handles.items():
            plugin = self._plugins.get(name)
            if plugin is None:
                continue
            try:
                await plugin.teardown(handle)
            except Exception as exc:  # noqa: BLE001
                print(
                    f"[CKS-MCP] ERROR: Plugin '{name}' failed to tear down: {exc}",
                    file=sys.stderr,
                )