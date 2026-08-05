"""
GossipPlugin — опциональный gossip-транспорт для p2p синхронизации сессий.

Требует пакет ``aiohttp`` (устанавливается через ``pip install cks-mcp[gossip]``).
Включается через ``CKS_GOSSIP_ENABLED=true``.

Обратная совместимость: существующие переменные ``CKS_GOSSIP_*``
продолжают работать без изменений.

Жизненный цикл плагина:

    handle = plugin.setup(runtime, config)   # строит компоненты, стартует сервис
    plugin.teardown(handle)                  # останавливает сервис и сервер

Метод ``setup`` возвращает ``GossipHandle`` или ``None``, если gossip
отключён или недоступен (нет ``replica_id``).
"""

from __future__ import annotations

import asyncio
import importlib
from typing import Any

from cks_runtime.config import RuntimeConfig
from cks_runtime.runtime import Runtime

from cks_mcp.gossip import GossipHandle, GossipSettings, setup_gossip
from cks_mcp.plugin import CksPlugin

__all__ = ["GossipPlugin"]


class GossipPlugin(CksPlugin):
    """Плагин gossip-транспорта для p2p синхронизации сессий."""

    name = "gossip"
    description = (
        "Optional gossip transport for peer-to-peer session synchronisation. "
        "Requires 'aiohttp' (pip install cks-mcp[gossip]). "
        "Enable with CKS_GOSSIP_ENABLED=true."
    )

    def is_available(self) -> bool:
        """Проверить наличие пакета ``aiohttp``."""
        try:
            importlib.import_module("aiohttp")
            return True
        except ImportError:
            return False

    def setup(self, runtime: Runtime, config: RuntimeConfig) -> GossipHandle | None:
        """
        Инициализировать и запустить gossip-подсистему.

        Настройки берутся из env (``CKS_GOSSIP_*``), как и раньше.
        Возвращает ``GossipHandle`` или ``None`` (если gossip отключён
        или runtime не имеет ``replica_id``).
        """
        settings = GossipSettings.from_env()
        handle = setup_gossip(runtime, settings)
        if handle is not None:
            # setup_gossip возвращает не запущенный handle;
            # запускаем его синхронно через asyncio.
            loop = asyncio.get_event_loop()
            loop.run_until_complete(handle.start())
        return handle

    def teardown(self, handle: Any) -> None:
        """Остановить gossip-сервис и сервер."""
        if handle is None:
            return
        loop = asyncio.get_event_loop()
        loop.run_until_complete(handle.stop())