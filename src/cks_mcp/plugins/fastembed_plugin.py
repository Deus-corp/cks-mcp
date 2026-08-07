"""
FastEmbedPlugin — провайдер эмбеддингов на базе fastembed + ONNX Runtime.

Активируется автоматически, если пакет ``fastembed`` установлен.
Поведение управляется переменной окружения ``CKS_EMBEDDING_PROVIDER``
(``fastembed`` по умолчанию | ``huggingface`` | ``stub``).

Обратная совместимость: существующие значения ``CKS_EMBEDDING_PROVIDER``
продолжают работать без изменений.
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import Any

from cks_runtime.config import RuntimeConfig
from cks_runtime.runtime import Runtime

from cks_mcp.plugin import CksPlugin

__all__ = ["FastEmbedPlugin"]


class FastEmbedPlugin(CksPlugin):
    """Плагин эмбеддингов на базе fastembed."""

    name = "fastembed"
    description = (
        "Embedding provider using fastembed + ONNX Runtime. "
        "Activated automatically when the 'fastembed' package is installed. "
        "Controlled by CKS_EMBEDDING_PROVIDER env var "
        "(fastembed [default] | huggingface | stub)."
    )

    def is_available(self) -> bool:
        """Проверить наличие пакета ``fastembed``."""
        try:
            importlib.import_module("fastembed")
            return True
        except ImportError:
            return False

    async def setup(self, runtime: Runtime, config: RuntimeConfig) -> Any:
        """
        Инициализировать embedding-клиент и установить его в runtime.

        Возвращает ``True`` при успехе, ``None`` если провайдер отключён
        через ``CKS_EMBEDDING_PROVIDER=stub``.
        """
        from cks_runtime.embedding.client import (
            FastEmbedEmbeddingClient,
            HuggingFaceEmbeddingClient,
        )

        embedding_provider = os.environ.get(
            "CKS_EMBEDDING_PROVIDER", "fastembed"
        ).lower()

        def _try_huggingface() -> HuggingFaceEmbeddingClient | None:
            try:
                return HuggingFaceEmbeddingClient()
            except Exception as exc:  # noqa: BLE001 — best-effort plugin init
                print(
                    f"[CKS-MCP] WARNING: HuggingFace embedding client unavailable: {exc}",
                    file=sys.stderr,
                )
                return None

        embedding_client = None

        if embedding_provider == "huggingface":
            embedding_client = _try_huggingface()
        elif embedding_provider == "stub":
            # Явно запрошена заглушка — не устанавливаем ничего.
            return None
        else:
            if embedding_provider != "fastembed":
                print(
                    f"[CKS-MCP] WARNING: Unknown CKS_EMBEDDING_PROVIDER="
                    f"{embedding_provider!r}, defaulting to fastembed.",
                    file=sys.stderr,
                )
            try:
                embedding_client = FastEmbedEmbeddingClient()
            except Exception as exc:  # noqa: BLE001 — best-effort plugin init
                print(
                    f"[CKS-MCP] WARNING: fastembed unavailable ({exc}); "
                    "trying HuggingFace.",
                    file=sys.stderr,
                )
                embedding_client = _try_huggingface()

        if embedding_client is None:
            print(
                "[CKS-MCP] WARNING: No embedding client configured — "
                "search_semantic will fall back to Runtime's non-semantic "
                "StubEmbeddingClient (SHA-256 based). "
                "Results will look like scores near 0 for everything, not real similarity. "
                "Install fastembed (`pip install cks-runtime[fastembed]`) or set HF_TOKEN "
                "and CKS_EMBEDDING_PROVIDER=huggingface to fix this.",
                file=sys.stderr,
            )
            return None

        runtime.embedding_client = embedding_client
        return True

    async def teardown(self, handle: Any) -> None:
        """Сбросить embedding_client — runtime перейдёт на StubEmbeddingClient."""
        # handle == None означает, что setup не устанавливал клиент.
        # Ничего не делаем: runtime сам использует заглушку при отсутствии клиента.