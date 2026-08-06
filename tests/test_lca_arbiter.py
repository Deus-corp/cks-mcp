"""Unit tests for cks_mcp.lca_arbiter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cks_mcp.lca_arbiter import (
    _branch_is_valid,
    _build_resolution_object,
    _resolution_object_id,
    classify_conflict,
    extract_delta,
    find_lca,
    resolve_with_lca,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_query_subgraph_response(nodes: list[dict], edges=None, total_found=None) -> dict:
    return {
        "subgraph": {
            "nodes": nodes,
            "edges": edges or [],
        },
        "total_found_nodes": total_found if total_found is not None else len(nodes),
    }


def _node(id: str, otype: str = "Concept", name: str = "", props: dict | None = None) -> dict:
    return {"id": id, "type": otype, "name": name or id, "props": props or {}}


def _edge(source: str, target: str, etype: str = "related_to") -> dict:
    return {"source": source, "target": target, "type": etype}


# ---------------------------------------------------------------------------
# _resolution_object_id & _build_resolution_object
# ---------------------------------------------------------------------------


class TestResolutionObject:
    def test_resolution_id_is_deterministic(self):
        id1 = _resolution_object_id("a", "b", "lca", "merge")
        id2 = _resolution_object_id("a", "b", "lca", "merge")
        assert id1 == id2

    def test_resolution_id_differs_for_different_strategies(self):
        id1 = _resolution_object_id("a", "b", "lca", "merge")
        id2 = _resolution_object_id("a", "b", "lca", "override")
        assert id1 != id2

    def test_build_resolution_object_shape(self):
        obj = _build_resolution_object(
            object_id_a="a",
            object_id_b="b",
            lca_id="lca",
            strategy="merge",
            rationale="test rationale",
        )
        assert obj["identity"]["type"] == "Resolution"
        assert obj["structure"]["strategy_applied"] == "merge"
        assert set(obj["structure"]["resolved_branches"]) == {"a", "b"}
        assert obj["structure"]["common_ancestor"] == "lca"
        assert obj["structure"]["rationale"] == "test rationale"
        assert obj["structure"]["depends_on"] == sorted(["a", "b"])


# ---------------------------------------------------------------------------
# classify_conflict
# ---------------------------------------------------------------------------


class TestClassifyConflict:
    def test_non_overlapping_when_node_ids_are_disjoint(self):
        delta_a = {"nodes": [_node("x")]}
        delta_b = {"nodes": [_node("y")]}
        assert classify_conflict(delta_a, delta_b) == "non_overlapping"

    def test_competing_claims_when_node_ids_overlap(self):
        delta_a = {"nodes": [_node("x"), _node("shared")]}
        delta_b = {"nodes": [_node("y"), _node("shared")]}
        assert classify_conflict(delta_a, delta_b) == "competing_claims"

    def test_empty_deltas_are_non_overlapping(self):
        assert classify_conflict({"nodes": []}, {"nodes": []}) == "non_overlapping"


# ---------------------------------------------------------------------------
# find_lca
# ---------------------------------------------------------------------------


class TestFindLCA:
    async def test_same_object_is_its_own_lca(self):
        runtime = MagicMock()
        result = await find_lca(runtime, "s1", "obj-1", "obj-1")
        assert result["found"] is True
        assert result["lca_id"] == "obj-1"
        assert result["depth_a"] == 0
        assert result["depth_b"] == 0

    async def test_common_ancestor_found_at_depth_1(self):
        runtime = MagicMock()

        async def _fake_query(rt, args):
            seed = args["seed_ids"][0]
            depth = args.get("depth", 0)
            if depth == 0:
                return _mock_query_subgraph_response([_node(seed)])
            # depth >= 1
            if seed == "a":
                nodes = [_node("a"), _node("shared")]
            else:
                nodes = [_node("b"), _node("shared")]
            return _mock_query_subgraph_response(nodes)

        with patch(
            "cks_mcp.lca_arbiter.query_subgraph_tool", side_effect=_fake_query
        ):
            result = await find_lca(runtime, "s1", "a", "b", max_depth=3)

        assert result["found"] is True
        assert result["lca_id"] == "shared"
        assert result["depth_a"] == 1
        assert result["depth_b"] == 1

    async def test_no_common_ancestor_within_max_depth(self):
        runtime = MagicMock()

        async def _fake_query(rt, args):
            seed = args["seed_ids"][0]
            nodes = [_node(seed)]  # only the seed itself, no shared nodes
            return _mock_query_subgraph_response(nodes)

        with patch(
            "cks_mcp.lca_arbiter.query_subgraph_tool", side_effect=_fake_query
        ):
            result = await find_lca(runtime, "s1", "a", "b", max_depth=3)

        assert result["found"] is False
        assert "no common ancestor" in result.get("reason", "")

    async def test_seed_not_found_in_session(self):
        runtime = MagicMock()

        async def _fake_query(rt, args):
            return {"error": "session_not_found"}

        with patch(
            "cks_mcp.lca_arbiter.query_subgraph_tool", side_effect=_fake_query
        ):
            result = await find_lca(runtime, "s1", "a", "b", max_depth=3)

        assert result["found"] is False
        assert result["reason"] is not None


# ---------------------------------------------------------------------------
# extract_delta
# ---------------------------------------------------------------------------


class TestExtractDelta:
    async def test_lca_equals_object_returns_single_node(self):
        runtime = MagicMock()

        async def _fake_query(rt, args):
            return _mock_query_subgraph_response([_node("obj-1")])

        with patch(
            "cks_mcp.lca_arbiter.query_subgraph_tool", side_effect=_fake_query
        ):
            delta = await extract_delta(runtime, "s1", "obj-1", "obj-1")

        assert len(delta["nodes"]) == 1
        assert delta["nodes"][0]["id"] == "obj-1"
        assert delta["relations"] == []

    async def test_extracts_branch_delta(self):
        runtime = MagicMock()

        async def _fake_query(rt, args):
            seeds = args["seed_ids"]
            if seeds == ["lca"]:
                depth = args.get("depth", 0)
                if depth == 0:
                    return _mock_query_subgraph_response([_node("lca")], total_found=1)
                # depth >= 1: tip is reachable from lca
                nodes = [_node("lca"), _node("tip")]
                edges = [_edge("lca", "tip", "derives_from")]
                return _mock_query_subgraph_response(nodes, edges, total_found=2)
            # Main delta query with both seeds
            nodes = [_node("lca"), _node("tip")]
            edges = [_edge("lca", "tip", "derives_from")]
            return _mock_query_subgraph_response(nodes, edges)

        with patch(
            "cks_mcp.lca_arbiter.query_subgraph_tool", side_effect=_fake_query
        ):
            delta = await extract_delta(runtime, "s1", "lca", "tip")

        assert len(delta["nodes"]) >= 1
        assert any(n["id"] == "tip" for n in delta["nodes"])

    async def test_unreachable_tip_falls_back_to_single_node(self):
        runtime = MagicMock()

        async def _fake_query(rt, args):
            if args["seed_ids"] == ["lca"]:
                return _mock_query_subgraph_response([_node("lca")], total_found=1)
            # The probe asks for seed_ids=["lca"] repeatedly with different depths,
            # then once with seed_ids=["lca", "tip"] and depth=1.
            return _mock_query_subgraph_response([_node("tip")])

        with patch(
            "cks_mcp.lca_arbiter.query_subgraph_tool", side_effect=_fake_query
        ):
            delta = await extract_delta(runtime, "s1", "lca", "tip")

        # Should fall back to just the tip node
        assert len(delta["nodes"]) == 1
        assert delta["nodes"][0]["id"] == "tip"


# ---------------------------------------------------------------------------
# _branch_is_valid
# ---------------------------------------------------------------------------


class TestBranchIsValid:
    async def test_valid_delta(self):
        runtime = MagicMock()
        delta = {
            "nodes": [_node("a", props={"value": 1})],
            "relations": [],
        }

        with patch(
            "cks_mcp.lca_arbiter.validate_knowledge",
            new=AsyncMock(return_value={"valid": True}),
        ):
            result = await _branch_is_valid(runtime, "s1", delta)

        assert result is True

    async def test_invalid_delta(self):
        runtime = MagicMock()
        delta = {
            "nodes": [_node("a")],
            "relations": [],
        }

        with patch(
            "cks_mcp.lca_arbiter.validate_knowledge",
            new=AsyncMock(return_value={"valid": False, "error": "validation_failed"}),
        ):
            result = await _branch_is_valid(runtime, "s1", delta)

        assert result is False

    async def test_validate_raises_returns_false(self):
        runtime = MagicMock()
        delta = {"nodes": [_node("a")], "relations": []}

        with patch(
            "cks_mcp.lca_arbiter.validate_knowledge",
            side_effect=RuntimeError("boom"),
        ):
            result = await _branch_is_valid(runtime, "s1", delta)

        assert result is False


# ---------------------------------------------------------------------------
# resolve_with_lca (integration)
# ---------------------------------------------------------------------------


class TestResolveWithLCA:
    async def test_no_lca_found_returns_unresolved(self):
        runtime = MagicMock()

        with patch(
            "cks_mcp.lca_arbiter.find_lca",
            new=AsyncMock(return_value={"found": False, "reason": "no ancestor"}),
        ):
            result = await resolve_with_lca(runtime, "s1", "a", "b")

        assert result.resolved is False
        assert "no ancestor" in (result.detail or "")

    async def test_non_overlapping_returns_resolved_without_winner(self):
        runtime = MagicMock()

        # Deltas without the LCA node itself — only the branch-specific changes
        delta_a = {"nodes": [_node("x")], "relations": []}
        delta_b = {"nodes": [_node("y")], "relations": []}

        with (
            patch(
                "cks_mcp.lca_arbiter.find_lca",
                new=AsyncMock(
                    return_value={"found": True, "lca_id": "lca", "depth_a": 1, "depth_b": 1}
                ),
            ),
            patch(
                "cks_mcp.lca_arbiter.extract_delta",
                new=AsyncMock(side_effect=[delta_a, delta_b]),
            ),
        ):
            result = await resolve_with_lca(runtime, "s1", "a", "b")

        assert result.resolved is True
        assert result.strategy == "non_overlapping"
        assert result.winner_object_id is None
        assert result.resolution_object is not None
        assert result.resolution_object["structure"]["strategy_applied"] == "non_overlapping"

    async def test_erroneous_branch_selects_valid_winner(self):
        runtime = MagicMock()

        delta_shared = {"nodes": [_node("lca"), _node("shared")], "relations": []}

        with (
            patch(
                "cks_mcp.lca_arbiter.find_lca",
                new=AsyncMock(
                    return_value={"found": True, "lca_id": "lca", "depth_a": 1, "depth_b": 1}
                ),
            ),
            patch(
                "cks_mcp.lca_arbiter.extract_delta",
                new=AsyncMock(side_effect=[delta_shared, delta_shared]),
            ),
            patch(
                "cks_mcp.lca_arbiter._branch_is_valid",
                new=AsyncMock(side_effect=[True, False]),  # a valid, b invalid
            ),
        ):
            result = await resolve_with_lca(runtime, "s1", "a", "b")

        assert result.resolved is True
        assert result.strategy == "erroneous_branch"
        assert result.winner_object_id == "a"

    async def test_extract_delta_error_returns_unresolved(self):
        runtime = MagicMock()

        with (
            patch(
                "cks_mcp.lca_arbiter.find_lca",
                new=AsyncMock(
                    return_value={"found": True, "lca_id": "lca", "depth_a": 1, "depth_b": 1}
                ),
            ),
            patch(
                "cks_mcp.lca_arbiter.extract_delta",
                new=AsyncMock(return_value={"nodes": [], "relations": [], "error": "boom"}),
            ),
        ):
            result = await resolve_with_lca(runtime, "s1", "a", "b")

        assert result.resolved is False
        assert "extract_delta failed" in (result.detail or "")