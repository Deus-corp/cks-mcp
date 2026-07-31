"""MCP tool implementations, one subpackage per tool (or tightly related pair).

Each subpackage exposes:
- handler.py  — the async implementation function(s)
- schema.py   — the MCP `name` / `description` / `inputSchema` for those tools
- __init__.py — re-exports the handler function(s) as the package's public API

cks_mcp.registry assembles these into the TOOLS dict the server dispatches on.
"""
