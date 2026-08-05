"""Input schema for the list_plugins tool."""

from __future__ import annotations

LIST_PLUGINS_SCHEMA = {
    "name": "list_plugins",
    "description": (
        "Return the list of all registered CKS MCP plugins with their availability "
        "status. 'available' means the plugin's optional dependencies are installed "
        "and it can be activated. "
        "Built-in plugins: 'fastembed' (embedding provider, requires fastembed package), "
        "'gossip' (p2p session sync, requires aiohttp + CKS_GOSSIP_ENABLED=true)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}