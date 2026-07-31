"""Unit tests for the construct_knowledge MCP tool."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_VALID_CKS_JSON = json.dumps(
    {
        "objects": [
            {
                "identity": {"id": "obj-sun", "type": "Concept", "name": "Sun"},
                "structure": {"description": "Star at the centre"},
            },
            {
                "identity": {"id": "obj-earth", "type": "Concept", "name": "Earth"},
                "structure": {"description": "Third planet"},
            },
            {
                "identity": {
                    "id": "rel-orbits",
                    "type": "Relation",
                    "name": "Earth orbits Sun",
                },
                "structure": {
                    "participants": ["obj-earth", "obj-sun"],
                    "relation_type": "orbits",
                },
            },
        ]
    }
)


def _make_construct_runtime() -> MagicMock:
    session = MagicMock()
    session.session_id = "sess-new"
    session.knowledge_structure = MagicMock()

    version = MagicMock()
    version.version_id = "ver-initial"

    runtime = MagicMock()
    runtime.create_session = AsyncMock(return_value=session)
    runtime.begin_transaction = MagicMock(return_value=MagicMock())
    runtime.commit_transaction = AsyncMock(return_value=version)
    runtime.core_bridge.serialize.return_value = _VALID_CKS_JSON
    return runtime


class TestConstructKnowledge:
    @pytest.mark.asyncio
    async def test_construct_success(self):
        from cks_mcp.tools.construct_knowledge.handler import construct_knowledge

        runtime = _make_construct_runtime()
        with patch(
            "cks_mcp.tools.construct_knowledge.handler._call_anthropic",
            return_value=_VALID_CKS_JSON,
        ):
            result = await construct_knowledge(
                runtime, {"text": "The Earth orbits the Sun."}
            )

        assert result.get("constructed") is True
        assert result["session_id"] == "sess-new"
        assert result["version_id"] == "ver-initial"
        assert result["objects_count"] == 2  # non-relation objects
        assert result["relations_count"] == 1

    @pytest.mark.asyncio
    async def test_construct_missing_text(self):
        from cks_mcp.tools.construct_knowledge.handler import construct_knowledge

        runtime = _make_construct_runtime()
        result = await construct_knowledge(runtime, {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_construct_llm_failure(self):
        from cks_mcp.tools.construct_knowledge.handler import construct_knowledge

        runtime = _make_construct_runtime()
        with patch(
            "cks_mcp.tools.construct_knowledge.handler._call_anthropic",
            side_effect=RuntimeError("network error"),
        ):
            result = await construct_knowledge(runtime, {"text": "Some text"})

        assert result.get("error") == "llm_output_parse_error" or "LLM" in result.get("message", "") or result.get("error") == "llm_call_failed" or "error" in result

    @pytest.mark.asyncio
    async def test_construct_invalid_json_from_llm(self):
        from cks_mcp.tools.construct_knowledge.handler import construct_knowledge

        runtime = _make_construct_runtime()
        with patch(
            "cks_mcp.tools.construct_knowledge.handler._call_anthropic",
            return_value="This is not JSON at all!",
        ):
            result = await construct_knowledge(runtime, {"text": "Some text"})

        assert "error" in result

    @pytest.mark.asyncio
    async def test_construct_invalid_cks_from_llm(self):
        from cks_mcp.tools.construct_knowledge.handler import construct_knowledge

        bad_json = json.dumps({
            "objects": [
                {
                    # Missing required "identity" key — will fail cks.parse
                    "structure": {"dangling": True}
                }
            ]
        })
        runtime = _make_construct_runtime()
        with patch(
            "cks_mcp.tools.construct_knowledge.handler._call_anthropic",
            return_value=bad_json,
        ):
            result = await construct_knowledge(runtime, {"text": "Bad structure"})

        # Should return a parse/validation error, NOT raise
        assert "error" in result

    @pytest.mark.asyncio
    async def test_construct_with_hint(self):
        from cks_mcp.tools.construct_knowledge.handler import construct_knowledge

        runtime = _make_construct_runtime()
        captured = {}

        def fake_call(prompt, model, max_tokens):
            captured["prompt"] = prompt
            return _VALID_CKS_JSON

        with patch("cks_mcp.tools.construct_knowledge.handler._call_anthropic", side_effect=fake_call):
            await construct_knowledge(
                runtime, {"text": "Some text", "hint": "focus on orbital mechanics"}
            )

        assert "orbital mechanics" in captured["prompt"]

    @pytest.mark.asyncio
    async def test_construct_model_override(self):
        from cks_mcp.tools.construct_knowledge.handler import construct_knowledge

        runtime = _make_construct_runtime()
        captured = {}

        def fake_call(prompt, model, max_tokens):
            captured["model"] = model
            return _VALID_CKS_JSON

        with patch("cks_mcp.tools.construct_knowledge.handler._call_anthropic", side_effect=fake_call):
            await construct_knowledge(
                runtime, {"text": "x", "model": "claude-opus-4-6"}
            )

        assert captured["model"] == "claude-opus-4-6"

    @pytest.mark.asyncio
    async def test_construct_json_wrapped_in_markdown_fence(self):
        from cks_mcp.tools.construct_knowledge.handler import construct_knowledge

        runtime = _make_construct_runtime()
        # LLM sometimes wraps output in ```json ... ```
        fenced = f"```json\n{_VALID_CKS_JSON}\n```"
        with patch(
            "cks_mcp.tools.construct_knowledge.handler._call_anthropic",
            return_value=fenced,
        ):
            result = await construct_knowledge(runtime, {"text": "Earth orbits Sun"})

        assert result.get("constructed") is True

    @pytest.mark.asyncio
    async def test_construct_result_includes_model_used(self):
        from cks_mcp.tools.construct_knowledge.handler import construct_knowledge

        runtime = _make_construct_runtime()
        with patch(
            "cks_mcp.tools.construct_knowledge.handler._call_anthropic",
            return_value=_VALID_CKS_JSON,
        ):
            result = await construct_knowledge(runtime, {"text": "test"})

        assert "model_used" in result
