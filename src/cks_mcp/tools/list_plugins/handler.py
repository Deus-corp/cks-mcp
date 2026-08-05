"""
list_plugins: return all registered plugins with their availability status.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cks_runtime.runtime import Runtime

if TYPE_CHECKING:
    from cks_mcp.plugin import PluginRegistry


# The registry is injected at import time from registry.py via module-level
# state rather than passed through the MCP tool arguments (which are
# user-supplied JSON and must not carry internal objects).
_plugin_registry: PluginRegistry | None = None


def set_plugin_registry(registry: PluginRegistry) -> None:
    """Called once from server.py after the registry is built."""
    global _plugin_registry  # noqa: PLW0603
    _plugin_registry = registry


async def list_plugins(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Return all registered plugins with name, description, and availability.

    ``available`` is ``True`` when the plugin's optional dependencies are
    installed.  It does not indicate whether the plugin was actually started
    (e.g. gossip may be available but not enabled via CKS_GOSSIP_ENABLED).
    """
    if _plugin_registry is None:
        return {"plugins": [], "available_count": 0, "total_count": 0}

    plugins = _plugin_registry.list_all()
    available_names = set(_plugin_registry.list_available())

    return {
        "plugins": plugins,
        "available_count": len(available_names),
        "total_count": len(plugins),
    }