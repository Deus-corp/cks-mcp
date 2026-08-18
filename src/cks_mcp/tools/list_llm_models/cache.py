"""Short-lived in-memory TTL cache for ``list_llm_models``.

cks-studio's Settings page calls ``list_llm_models`` on every render to
populate its model picker, which -- for the ``"ollama"`` provider --
hits a live ``GET {CKS_OLLAMA_HOST}/api/tags`` every single time (the
"anthropic"/"openai_compatible" branches already just return a
hardcoded list, no network call, so caching them matters far less, but
costs nothing to include). This cache lets repeated UI polls reuse a
recent result instead of re-querying the provider on every render.

Deliberately tiny and process-local (a plain dict + lock, same shape
as ``llm_telemetry``'s ring buffer) -- no external cache dependency
for something this small and short-lived.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

# Default TTL, overridable via CKS_LLM_MODELS_TTL_SECONDS for
# deployments that want faster/slower refresh. Kept short by default
# (5 minutes) since the whole point is de-duping rapid UI polling, not
# hiding a genuinely changed model lineup for long.
_DEFAULT_TTL_SECONDS = 300.0


def _ttl_seconds() -> float:
    raw = os.environ.get("CKS_LLM_MODELS_TTL_SECONDS", "")
    if not raw.strip():
        return _DEFAULT_TTL_SECONDS
    try:
        ttl = float(raw)
    except ValueError:
        return _DEFAULT_TTL_SECONDS
    return ttl if ttl >= 0 else _DEFAULT_TTL_SECONDS


class ListLlmModelsCache:
    """TTL-keyed cache of ``{"provider": ..., "models": [...]}`` results.

    The cache key is a *fingerprint* of the provider config that could
    change what ``list_llm_models`` returns -- provider selection plus
    whichever endpoint URL that provider would be queried against --
    deliberately excluding API key values so a key rotation neither
    needs to bust the cache nor risks a key value ever being used as
    (or stored in) a cache key. Any change to the fingerprint (e.g.
    switching CKS_OLLAMA_HOST, or flipping CKS_LLM_PROVIDER) is a
    cache miss, so stale entries for an old config are simply never
    read again rather than needing explicit invalidation.
    """

    def __init__(self, *, clock: Any = time.monotonic) -> None:
        self._entries: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def get(self, key: str) -> dict[str, Any] | None:
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if now >= expires_at:
                del self._entries[key]
                return None
            return value

    def set(self, key: str, value: dict[str, Any]) -> None:
        ttl = _ttl_seconds()
        if ttl <= 0:
            # TTL of 0 (or a bad/negative override) disables caching
            # outright rather than caching-with-instant-expiry, so
            # CKS_LLM_MODELS_TTL_SECONDS=0 is a legible "off" switch.
            return
        expires_at = self._clock() + ttl
        with self._lock:
            self._entries[key] = (expires_at, value)

    def clear(self) -> None:
        """Drop all cached entries. Exposed for tests."""
        with self._lock:
            self._entries.clear()


# Process-level singleton, mirroring llm_telemetry's convention.
list_llm_models_cache = ListLlmModelsCache()

__all__ = ["ListLlmModelsCache", "list_llm_models_cache"]
