"""
GossipPlugin — optional gossip transport for p2p session synchronisation.

Requires the ``aiohttp`` package (install with ``pip install cks-mcp[gossip]``).
Enabled via ``CKS_GOSSIP_ENABLED=true``.

Backward compatibility: existing ``CKS_GOSSIP_*`` environment variables
continue to work unchanged.

Plugin lifecycle:

    handle = await plugin.setup(runtime, config)   # builds components, starts the service
    await plugin.teardown(handle)                  # stops the service and server

The ``setup`` method returns a ``GossipHandle`` or ``None`` if gossip is
disabled or unavailable (no ``replica_id``).
"""

from __future__ import annotations

import importlib
from typing import Any

from cks_runtime.config import RuntimeConfig
from cks_runtime.runtime import Runtime

from cks_mcp.gossip import GossipHandle, GossipSettings, setup_gossip
from cks_mcp.plugin import CksPlugin

__all__ = ["GossipPlugin"]


class GossipPlugin(CksPlugin):
    """Gossip transport plugin for peer-to-peer session synchronisation."""

    name = "gossip"
    description = (
        "Optional gossip transport for peer-to-peer session synchronisation. "
        "Requires 'aiohttp' (pip install cks-mcp[gossip]). "
        "Enable with CKS_GOSSIP_ENABLED=true."
    )

    def is_available(self) -> bool:
        """Check whether the ``aiohttp`` package is installed."""
        try:
            importlib.import_module("aiohttp")
            return True
        except Exception:  # noqa: BLE001 — best-effort check, never crash
            return False

    async def setup(self, runtime: Runtime, config: RuntimeConfig) -> GossipHandle | None:
        """
        Initialise and start the gossip subsystem.

        Settings are read from the environment (``CKS_GOSSIP_*``), exactly as
        before. Returns a ``GossipHandle`` or ``None`` if gossip is disabled
        or the runtime has no ``replica_id``.
        """
        settings = GossipSettings.from_env()
        handle = setup_gossip(runtime, settings)
        if handle is not None:
            await handle.start()
        return handle

    async def teardown(self, handle: Any) -> None:
        """Stop the gossip service and server."""
        if handle is None:
            return
        await handle.stop()