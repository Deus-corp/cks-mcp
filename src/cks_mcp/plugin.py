"""
CKS Plugin Framework — базовый класс плагина и реестр плагинов.

Плагин — это опциональная функциональность, которая:
  * проверяет наличие своих зависимостей через ``is_available()``;
  * инициализируется через ``setup(runtime, config)`` и возвращает handle;
  * корректно останавливается через ``teardown(handle)``.

``PluginRegistry`` хранит зарегистрированные плагины и управляет их
жизненным циклом (``setup_all`` / ``teardown_all``).

Добавить новый плагин:
  1. Создать класс ``MyPlugin(CksPlugin)`` в ``cks_mcp/plugins/``.
  2. Зарегистрировать его в ``server.py``: ``registry.register(MyPlugin())``.
  Изменять cks-runtime или cks-core не нужно.
"""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from typing import Any

from cks_runtime.config import RuntimeConfig
from cks_runtime.runtime import Runtime

__all__ = ["CksPlugin", "PluginRegistry"]


class CksPlugin(ABC):
    """Абстрактный базовый класс для плагинов cks-mcp."""

    #: Уникальное машинное имя плагина (snake_case).
    name: str

    #: Человекочитаемое описание.
    description: str

    @abstractmethod
    def is_available(self) -> bool:
        """
        Проверить, установлены ли необходимые зависимости.

        Не должен бросать исключений — только возвращать ``True``/``False``.
        """

    @abstractmethod
    def setup(self, runtime: Runtime, config: RuntimeConfig) -> Any:
        """
        Инициализировать плагин.

        Вызывается только если ``is_available()`` вернул ``True``.
        Возвращает handle (любой объект), который передаётся в ``teardown``.
        Может вернуть ``None``, если плагин решил не запускаться
        (например, из-за env-флага вроде ``CKS_GOSSIP_ENABLED``).
        """

    @abstractmethod
    def teardown(self, handle: Any) -> None:
        """
        Корректно остановить плагин.

        ``handle`` — значение, ранее возвращённое ``setup``.
        Если ``handle`` равен ``None``, плагин не был запущен; реализация
        должна это учитывать и ничего не делать.
        """


class PluginRegistry:
    """
    Реестр плагинов cks-mcp.

    Жизненный цикл::

        registry = PluginRegistry()
        registry.register(FastEmbedPlugin())
        registry.register(GossipPlugin())

        # при старте
        handles = await registry.setup_all(runtime, config)

        # при остановке
        await registry.teardown_all(handles)
    """

    def __init__(self) -> None:
        self._plugins: dict[str, CksPlugin] = {}

    def register(self, plugin: CksPlugin) -> None:
        """Добавить плагин в реестр."""
        self._plugins[plugin.name] = plugin

    def list_all(self) -> list[dict[str, Any]]:
        """
        Вернуть информацию обо всех зарегистрированных плагинах.

        Каждый элемент: ``{"name": ..., "description": ..., "available": bool}``.
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
        """Вернуть имена плагинов, для которых ``is_available()`` == True."""
        return [p.name for p in self._plugins.values() if p.is_available()]

    def setup_all(self, runtime: Runtime, config: RuntimeConfig) -> dict[str, Any]:
        """
        Инициализировать все доступные плагины.

        Возвращает словарь ``{name: handle}`` для всех плагинов, у которых
        ``is_available()`` == True (handle может быть ``None``, если плагин
        решил не запускаться).
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
        """Остановить все плагины, для которых есть handle."""
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