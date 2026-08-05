# Plugin Framework

`cks-mcp` ships a lightweight **Plugin Framework** that lets you add optional
functionality without touching `cks-core` or `cks-runtime`.

A plugin:

- **declares** whether its optional dependencies are installed (`is_available`),
- **initialises** itself against the live `Runtime` and `RuntimeConfig` (`setup`), and
- **cleans up** gracefully on shutdown (`teardown`).

Plugins are registered in `server.py` and exposed to LLMs via the
[`list_plugins`](tools/export-and-audit.md#list_plugins) tool.

---

## `CksPlugin` interface

```python
# src/cks_mcp/plugin.py
from abc import ABC, abstractmethod
from typing import Any
from cks_runtime.config import RuntimeConfig
from cks_runtime.runtime import Runtime

class CksPlugin(ABC):
    name: str          # unique snake_case identifier
    description: str   # human-readable, shown by list_plugins

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if optional deps are present. Must not raise."""

    @abstractmethod
    def setup(self, runtime: Runtime, config: RuntimeConfig) -> Any:
        """
        Initialise the plugin.

        Called only when is_available() is True.
        Returns a *handle* (any object) passed later to teardown.
        Return None to signal "deps present but plugin decided not to start"
        (e.g. CKS_GOSSIP_ENABLED not set).
        """

    @abstractmethod
    def teardown(self, handle: Any) -> None:
        """
        Stop the plugin.

        handle is whatever setup() returned.
        If handle is None the plugin was not started; implementations must
        handle that case and do nothing.
        """
```

---

## `PluginRegistry`

```python
registry = PluginRegistry()
registry.register(MyPlugin())

# at startup
handles = registry.setup_all(runtime, config)

# at shutdown
registry.teardown_all(handles)
```

| Method | Description |
|--------|-------------|
| `register(plugin)` | Add a plugin. Last writer wins on `plugin.name`. |
| `list_all()` | `[{name, description, available}, …]` — all registered plugins. |
| `list_available()` | `[name, …]` — names where `is_available()` is `True`. |
| `setup_all(runtime, config)` | Init all available plugins; returns `{name: handle}`. Errors are logged to stderr and skipped. |
| `teardown_all(handles)` | Call `teardown` for each handle. Errors logged and skipped. |

---

## Built-in plugins

### `FastEmbedPlugin`

**File:** `src/cks_mcp/plugins/fastembed_plugin.py`

Activates the `fastembed` + ONNX Runtime embedding backend used by
`search_semantic`.

```python
class FastEmbedPlugin(CksPlugin):
    name = "fastembed"

    def is_available(self) -> bool:
        # True when `import fastembed` succeeds
        ...

    def setup(self, runtime, config):
        # Reads CKS_EMBEDDING_PROVIDER (fastembed | huggingface | stub)
        # Sets runtime.embedding_client
        # Returns True on success, None when provider == "stub"
        ...

    def teardown(self, handle):
        # No-op: runtime falls back to StubEmbeddingClient automatically
        ...
```

**Install:** `pip install cks-mcp[fastembed]`  
**Toggle:** `CKS_EMBEDDING_PROVIDER=fastembed` (default) | `huggingface` | `stub`

---

### `GossipPlugin`

**File:** `src/cks_mcp/plugins/gossip_plugin.py`

Activates the optional p2p gossip transport for multi-replica session
synchronisation.

```python
class GossipPlugin(CksPlugin):
    name = "gossip"

    def is_available(self) -> bool:
        # True when `import aiohttp` succeeds
        ...

    def setup(self, runtime, config):
        # Reads CKS_GOSSIP_* env vars
        # Calls setup_gossip() and starts the handle
        # Returns GossipHandle or None (when CKS_GOSSIP_ENABLED != "true")
        ...

    def teardown(self, handle):
        # Calls handle.stop() if handle is not None
        ...
```

**Install:** `pip install cks-mcp[gossip]`  
**Enable:** `CKS_GOSSIP_ENABLED=true`  
**Config:** `CKS_GOSSIP_HOST`, `CKS_GOSSIP_PORT`, `CKS_GOSSIP_PEERS`, `CKS_GOSSIP_SECRET`

---

## Writing a new plugin

1. Create `src/cks_mcp/plugins/my_plugin.py`:

```python
from __future__ import annotations

import importlib
from typing import Any

from cks_runtime.config import RuntimeConfig
from cks_runtime.runtime import Runtime

from cks_mcp.plugin import CksPlugin

__all__ = ["MyPlugin"]


class MyPlugin(CksPlugin):
    name = "my_plugin"
    description = "Does something optional."

    def is_available(self) -> bool:
        try:
            importlib.import_module("some_optional_dep")
            return True
        except ImportError:
            return False

    def setup(self, runtime: Runtime, config: RuntimeConfig) -> Any:
        import some_optional_dep  # noqa: PLC0415
        handle = some_optional_dep.start()
        return handle

    def teardown(self, handle: Any) -> None:
        if handle is None:
            return
        handle.stop()
```

2. Export it from `src/cks_mcp/plugins/__init__.py`:

```python
from .my_plugin import MyPlugin as MyPlugin
```

3. Register it in `src/cks_mcp/server.py` (inside `main()`):

```python
registry.register(MyPlugin())
```

That's it — no changes to `cks-core` or `cks-runtime` required. The plugin
will appear in `list_plugins` output automatically.

---

## `list_plugins` tool

Query the live plugin registry from any LLM:

```
Use cks-mcp to list_plugins
```

Response example:

```json
{
  "plugins": [
    {
      "name": "fastembed",
      "description": "Embedding provider using fastembed + ONNX Runtime…",
      "available": true
    },
    {
      "name": "gossip",
      "description": "Optional gossip transport for peer-to-peer session synchronisation…",
      "available": false
    }
  ],
  "available_count": 1,
  "total_count": 2
}
```

`available: true` means the plugin's optional dependencies are installed.
It does **not** mean the plugin was actually started (e.g. gossip requires
`CKS_GOSSIP_ENABLED=true` to start, even when `aiohttp` is present).

---

## Testing your plugin

Follow the pattern in `tests/plugins/`:

```python
from unittest.mock import MagicMock, patch
from cks_mcp.plugins.my_plugin import MyPlugin

def test_is_available_true():
    with patch("importlib.import_module", return_value=MagicMock()):
        assert MyPlugin().is_available() is True

def test_is_available_false():
    with patch("importlib.import_module", side_effect=ImportError):
        assert MyPlugin().is_available() is False

def test_setup_calls_start():
    plugin = MyPlugin()
    runtime, config = MagicMock(), MagicMock()
    fake_handle = MagicMock()
    with patch("some_optional_dep.start", return_value=fake_handle):
        handle = plugin.setup(runtime, config)
    assert handle is fake_handle

def test_teardown_none_is_noop():
    MyPlugin().teardown(None)  # must not raise
```