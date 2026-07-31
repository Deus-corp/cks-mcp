"""Unit tests for the query_subgraph MCP tool."""

from __future__ import annotations

from dataclasses import dataclass

from cks.core import (
    CanonicalRelation,
    KnowledgeObject,
    KnowledgeStructure,
    ObjectIdentity,
)


def _obj(oid: str, otype: str = "Concept", name: str = "", **structure) -> KnowledgeObject:
    return KnowledgeObject(
        identity=ObjectIdentity(id=oid, type=otype, name=name or oid),
        structure=dict(structure),
    )


def _rel(oid: str, participants: list[str], relation_type: str = "links") -> CanonicalRelation:
    return CanonicalRelation(
        identity=ObjectIdentity(id=oid, type="Relation", name=oid),
        participants=participants,
        relation_type=relation_type,
    )


@dataclass
class FakeSubgraphResult:
    structure: KnowledgeStructure
    total_found_nodes: int
    returned_nodes: int
    is_truncated: bool
    truncation_reason: str | None = None
    suggested_next_seed: str | None = None


def _fake_result(*objects) -> FakeSubgraphResult:
    ks = KnowledgeStructure(list(objects))
    non_rel = [o for o in ks.objects if not isinstance(o, CanonicalRelation)]
    return FakeSubgraphResult(
        structure=ks,
        total_found_nodes=len(non_rel),
        returned_nodes=len(non_rel),
        is_truncated=False,
    )


class TestStructureFilters:
    from cks_mcp.tools.query_subgraph.handler import _apply_structure_filter

    def setup_method(self):
        from cks_mcp.tools.query_subgraph.handler import _apply_structure_filter
        self._filter = _apply_structure_filter

    def test_filter_keeps_matching_objects(self):
        a = _obj("a", status="active")
        b = _obj("b", status="inactive")
        c = _obj("c", status="active")  # seed
        result = self._filter(_fake_result(a, b, c), ["c"], {"status": "active"})
        ids = {o.identity.id for o in result.structure.objects}
        assert "a" in ids
        assert "b" not in ids
        assert "c" in ids

    def test_seed_always_survives_filter(self):
        seed = _obj("seed", status="inactive")
        other = _obj("other", status="active")
        result = self._filter(_fake_result(seed, other), ["seed"], {"status": "active"})
        ids = {o.identity.id for o in result.structure.objects}
        assert "seed" in ids

    def test_relation_kept_when_both_participants_survive(self):
        a = _obj("a", domain="bio")
        b = _obj("b", domain="bio")
        r = _rel("r", ["a", "b"])
        result = self._filter(_fake_result(a, b, r), ["a"], {"domain": "bio"})
        ids = {o.identity.id for o in result.structure.objects}
        assert "r" in ids

    def test_relation_dropped_when_participant_filtered(self):
        a = _obj("a", domain="bio")
        b = _obj("b", domain="chem")  # will be filtered
        r = _rel("r", ["a", "b"])
        result = self._filter(_fake_result(a, b, r), ["a"], {"domain": "bio"})
        ids = {o.identity.id for o in result.structure.objects}
        assert "r" not in ids

    def test_multi_field_and_logic(self):
        a = _obj("a", status="active", domain="bio")
        b = _obj("b", status="active", domain="chem")
        c = _obj("c", status="inactive", domain="bio")
        seed = _obj("s", status="active", domain="bio")
        result = self._filter(
            _fake_result(a, b, c, seed),
            ["s"],
            {"status": "active", "domain": "bio"},
        )
        ids = {o.identity.id for o in result.structure.objects}
        assert "a" in ids   # both match
        assert "b" not in ids  # domain mismatch
        assert "c" not in ids  # status mismatch
        assert "s" in ids   # seed

    def test_empty_filters_keeps_all(self):
        a = _obj("a", status="active")
        b = _obj("b", status="inactive")
        result = self._filter(_fake_result(a, b), ["a"], {})
        ids = {o.identity.id for o in result.structure.objects}
        assert "a" in ids
        assert "b" in ids

    def test_returned_nodes_count_updated(self):
        a = _obj("a", status="active")
        b = _obj("b", status="inactive")
        c = _obj("c", status="active")
        result = self._filter(_fake_result(a, b, c), ["c"], {"status": "active"})
        assert result.returned_nodes == 2  # a and c

    def test_is_truncated_set_when_filtered(self):
        a = _obj("a", status="active")
        b = _obj("b", status="inactive")
        result = self._filter(_fake_result(a, b), ["a"], {"status": "active"})
        # total_found_nodes=2, returned_nodes=1 → truncated
        assert result.is_truncated is True

    def test_numeric_field_comparison(self):
        high = _obj("high", score=90)
        low = _obj("low", score=40)
        seed = _obj("seed", score=90)
        result = self._filter(_fake_result(high, low, seed), ["seed"], {"score": 90})
        ids = {o.identity.id for o in result.structure.objects}
        assert "high" in ids
        assert "low" not in ids

    def test_boolean_field_comparison(self):
        active = _obj("active", enabled=True)
        inactive = _obj("inactive", enabled=False)
        seed = _obj("seed", enabled=True)
        result = self._filter(
            _fake_result(active, inactive, seed), ["seed"], {"enabled": True}
        )
        ids = {o.identity.id for o in result.structure.objects}
        assert "active" in ids
        assert "inactive" not in ids
