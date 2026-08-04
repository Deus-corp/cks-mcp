"""Unit tests for the resolve_gossip_conflict MCP tool."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.asyncio

_CONFLICTS = [
    {"object_id": "obj-1", "branch_a": {"identity": "a"}, "branch_b": {"identity": "b"}},
]

_MERGED_RESULT = {"merged": True, "version_id": "v9"}
_CONFLICT_PROBE = {"merged": False, "conflicts": _CONFLICTS}

_VALID_RESOLUTIONS = json.dumps({"obj-1": "branch_a"})


def _make_runtime() -> MagicMock:
    """resolve_gossip_conflict itself never touches the runtime directly --
    every session lookup happens either in registry.py's require_open_session
    middleware (not exercised by these handler-level tests) or inside the
    merge_branch() calls this handler makes, which we mock out below."""
    return MagicMock()


class TestProbeOnly:
    async def test_no_conflict_returns_merge_result_unchanged(self):
        from cks_mcp.tools.resolve_gossip_conflict.handler import (
            resolve_gossip_conflict,
        )

        runtime = _make_runtime()
        with patch(
            "cks_mcp.tools.resolve_gossip_conflict.handler.merge_branch",
            AsyncMock(return_value=_MERGED_RESULT),
        ):
            result = await resolve_gossip_conflict(
                runtime, {"target_session_id": "t1", "source_session_id": "s1"}
            )
        assert result == _MERGED_RESULT

    async def test_conflict_without_auto_resolve_returns_conflicts_and_policy(self):
        from cks_mcp.tools.resolve_gossip_conflict.handler import (
            resolve_gossip_conflict,
        )

        runtime = _make_runtime()
        with patch(
            "cks_mcp.tools.resolve_gossip_conflict.handler.merge_branch",
            AsyncMock(return_value=_CONFLICT_PROBE),
        ) as mock_merge:
            result = await resolve_gossip_conflict(
                runtime, {"target_session_id": "t1", "source_session_id": "s1"}
            )
        mock_merge.assert_awaited_once()
        assert result["merged"] is False
        assert result["conflicts"] == _CONFLICTS
        assert "policy" in result

    async def test_probe_passes_through_missing_parameter_from_merge_branch(self):
        """No local session/field validation in the handler -- a missing
        target_session_id is reported by the downstream merge_branch()
        call, same as merge_branch reports it for itself."""
        from cks_mcp.tools.resolve_gossip_conflict.handler import (
            resolve_gossip_conflict,
        )

        runtime = _make_runtime()
        missing = {"error": "missing_parameter", "parameter": "target_session_id"}
        with patch(
            "cks_mcp.tools.resolve_gossip_conflict.handler.merge_branch",
            AsyncMock(return_value=missing),
        ):
            result = await resolve_gossip_conflict(runtime, {"source_session_id": "s1"})
        assert result == missing

    async def test_unexpected_no_merge_no_conflicts_returns_probe(self):
        from cks_mcp.tools.resolve_gossip_conflict.handler import (
            resolve_gossip_conflict,
        )

        runtime = _make_runtime()
        odd_probe = {"merged": False, "conflicts": []}
        with patch(
            "cks_mcp.tools.resolve_gossip_conflict.handler.merge_branch",
            AsyncMock(return_value=odd_probe),
        ):
            result = await resolve_gossip_conflict(
                runtime, {"target_session_id": "t1", "source_session_id": "s1"}
            )
        assert result == odd_probe


class TestAutoResolve:
    async def test_success_calls_llm_then_remerges_with_resolutions(self):
        from cks_mcp.tools.resolve_gossip_conflict.handler import (
            resolve_gossip_conflict,
        )

        runtime = _make_runtime()
        merge_mock = AsyncMock(side_effect=[_CONFLICT_PROBE, _MERGED_RESULT])
        with patch(
            "cks_mcp.tools.resolve_gossip_conflict.handler.merge_branch", merge_mock
        ), patch(
            "cks_mcp.tools.resolve_gossip_conflict.handler._call_anthropic",
            return_value=_VALID_RESOLUTIONS,
        ):
            result = await resolve_gossip_conflict(
                runtime,
                {
                    "target_session_id": "t1",
                    "source_session_id": "s1",
                    "auto_resolve": True,
                },
            )
        assert result == _MERGED_RESULT
        assert merge_mock.await_count == 2
        second_call_kwargs = merge_mock.await_args_list[1].args[1]
        assert second_call_kwargs["resolutions"] == {"obj-1": "branch_a"}

    async def test_llm_output_not_json_returns_internal_error(self):
        from cks_mcp.tools.resolve_gossip_conflict.handler import (
            resolve_gossip_conflict,
        )

        runtime = _make_runtime()
        with patch(
            "cks_mcp.tools.resolve_gossip_conflict.handler.merge_branch",
            AsyncMock(return_value=_CONFLICT_PROBE),
        ), patch(
            "cks_mcp.tools.resolve_gossip_conflict.handler._call_anthropic",
            return_value="not json at all",
        ):
            result = await resolve_gossip_conflict(
                runtime,
                {
                    "target_session_id": "t1",
                    "source_session_id": "s1",
                    "auto_resolve": True,
                },
            )
        assert result.get("error") == "internal_error"

    async def test_llm_call_raises_returns_internal_error(self):
        from cks_mcp.tools.resolve_gossip_conflict.handler import (
            resolve_gossip_conflict,
        )

        runtime = _make_runtime()
        with patch(
            "cks_mcp.tools.resolve_gossip_conflict.handler.merge_branch",
            AsyncMock(return_value=_CONFLICT_PROBE),
        ), patch(
            "cks_mcp.tools.resolve_gossip_conflict.handler._call_anthropic",
            side_effect=RuntimeError("ANTHROPIC_API_KEY environment variable is not set."),
        ):
            result = await resolve_gossip_conflict(
                runtime,
                {
                    "target_session_id": "t1",
                    "source_session_id": "s1",
                    "auto_resolve": True,
                },
            )
        assert result.get("error") == "internal_error"

    async def test_already_merged_skips_llm_entirely(self):
        from cks_mcp.tools.resolve_gossip_conflict.handler import (
            resolve_gossip_conflict,
        )

        runtime = _make_runtime()
        with patch(
            "cks_mcp.tools.resolve_gossip_conflict.handler.merge_branch",
            AsyncMock(return_value=_MERGED_RESULT),
        ), patch(
            "cks_mcp.tools.resolve_gossip_conflict.handler._call_anthropic"
        ) as mock_call:
            result = await resolve_gossip_conflict(
                runtime,
                {
                    "target_session_id": "t1",
                    "source_session_id": "s1",
                    "auto_resolve": True,
                },
            )
        mock_call.assert_not_called()
        assert result == _MERGED_RESULT


class TestProviderDispatch:
    """CKS_LLM_PROVIDER dispatch should match arbitrate_inference_conflict's
    'auto' | 'ollama' | 'anthropic' behavior (ADR-006), not just always
    fall through to Anthropic for anything but an explicit 'ollama'."""

    async def test_auto_uses_ollama_when_available(self, monkeypatch):
        from cks_mcp.tools.resolve_gossip_conflict import handler

        monkeypatch.delenv("CKS_LLM_PROVIDER", raising=False)
        with patch.object(handler.llm_providers, "ollama_available", return_value=True), patch(
            "cks_mcp.tools.resolve_gossip_conflict.handler._call_ollama",
            return_value=_VALID_RESOLUTIONS,
        ) as mock_ollama, patch(
            "cks_mcp.tools.resolve_gossip_conflict.handler._call_anthropic"
        ) as mock_anthropic:
            raw = handler._call_llm("prompt", model=None, max_tokens=100)
        assert raw == _VALID_RESOLUTIONS
        mock_ollama.assert_called_once()
        mock_anthropic.assert_not_called()

    async def test_auto_falls_back_to_anthropic_when_ollama_unavailable(self, monkeypatch):
        from cks_mcp.tools.resolve_gossip_conflict import handler

        monkeypatch.delenv("CKS_LLM_PROVIDER", raising=False)
        with patch.object(
            handler.llm_providers, "ollama_available", return_value=False
        ), patch(
            "cks_mcp.tools.resolve_gossip_conflict.handler._call_anthropic",
            return_value=_VALID_RESOLUTIONS,
        ) as mock_anthropic:
            raw = handler._call_llm("prompt", model=None, max_tokens=100)
        assert raw == _VALID_RESOLUTIONS
        mock_anthropic.assert_called_once()

    async def test_explicit_ollama_skips_availability_check(self, monkeypatch):
        from cks_mcp.tools.resolve_gossip_conflict import handler

        monkeypatch.setenv("CKS_LLM_PROVIDER", "ollama")
        with patch.object(handler.llm_providers, "ollama_available") as mock_avail, patch(
            "cks_mcp.tools.resolve_gossip_conflict.handler._call_ollama",
            return_value=_VALID_RESOLUTIONS,
        ) as mock_ollama:
            handler._call_llm("prompt", model=None, max_tokens=100)
        mock_avail.assert_not_called()
        mock_ollama.assert_called_once()

    async def test_unknown_provider_raises(self, monkeypatch):
        from cks_mcp.tools.resolve_gossip_conflict import handler

        monkeypatch.setenv("CKS_LLM_PROVIDER", "bogus")
        with pytest.raises(RuntimeError, match="Unknown CKS_LLM_PROVIDER"):
            handler._call_llm("prompt", model=None, max_tokens=100)