"""
Stable, cwd-independent data directory for cks-mcp.

Resolved once at import time from, in order:
1. CKS_MCP_DATA_DIR environment variable
2. ~/.cks-mcp
"""

import os
from pathlib import Path

_DATA_DIR = Path(
    os.environ.get("CKS_MCP_DATA_DIR", Path.home() / ".cks-mcp")
).expanduser().resolve()


def data_dir() -> Path:
    """Return the absolute path to the cks-mcp data directory."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    return _DATA_DIR