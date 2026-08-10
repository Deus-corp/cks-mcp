"""Shared, tool-calling-capable LLM client (cks-mcp ADR-011 §6).

See ``cks_mcp.llm.client`` for the actual provider-routing logic.
"""

from __future__ import annotations

from cks_mcp.llm.client import LLMClient, LLMProviderUnavailable

__all__ = ["LLMClient", "LLMProviderUnavailable"]
