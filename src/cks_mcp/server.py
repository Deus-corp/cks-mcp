"""
CKS MCP Server — JSON-RPC over stdio.

This is a thin wrapper that delegates all operations to the
MCPHandler and MCPAdapter provided by cks‑runtime.
"""

from __future__ import annotations

import asyncio

from cks_runtime.runtime import Runtime
from cks_runtime.adapters.mcp.handlers import MCPHandler
from cks_runtime_core import CksCoreAdapter


def main() -> None:
    """Entry point for the MCP server."""
    runtime = Runtime(core=CksCoreAdapter())
    handler = MCPHandler(runtime)
    asyncio.run(handler.run())


if __name__ == "__main__":
    main()