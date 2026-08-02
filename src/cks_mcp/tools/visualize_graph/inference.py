"""
Builds a Mermaid diagram from ``explain_inference()``'s recursive result,
for ``visualize_graph``'s ``mode="inference"``.

``explain_inference`` (see ``cks.constraints.reasoning`` in cks-core)
already returns the *entire* recursive chain behind one object -- every
active/superseded ``InferenceStep`` back to base facts -- in a single
call. This module therefore only ever walks that one dict per requested
target; it never re-invokes the Core to expand a premise that's already
part of the payload it was given.

Field names are read as literal string keys straight off the returned
dict (``"premises"``, ``"conclusion"``, ``"cites_step"``, ...), the same
way ``explain_diff``'s handler reads ``InferenceStep`` structure fields,
rather than importing ``cks.constraints.reasoning``'s private
``_PREMISES_KEY``-style constants -- those are an internal implementation
detail of cks-core's reasoning module, not a published contract.
"""

from __future__ import annotations

from typing import Any

# A rendered edge, kept as a plain tuple so it can double as its own
# dedup key: (source_alias_id, target_alias_id, label, dashed).
_Edge = tuple[str, str, str, bool]


class InferenceGraphBuilder:
    """
    Accumulates Mermaid nodes/edges while walking one or more
    ``explain_inference()`` results against a node budget.

    One instance is shared across every target_id in a single
    ``visualize_graph(mode="inference")`` call, so that nodes reached
    from more than one chain (a shared base fact, a step cited from two
    places) are only added -- and only counted against the budget --
    once, and their premises are only walked once.
    """

    def __init__(self, structure: Any, *, max_objects: int, include_superseded: bool) -> None:
        self._structure = structure
        self._max_objects = max_objects
        self._include_superseded = include_superseded

        # object_id / step_id -> render metadata.
        self._object_nodes: dict[str, dict[str, Any]] = {}
        self._step_nodes: dict[str, dict[str, Any]] = {}

        self._edge_keys: set[_Edge] = set()
        self._edges: list[_Edge] = []

        # Ids that have been counted against the budget (whether or not
        # they made it in) vs. ids whose premises/steps have already
        # been recursed into, so a diamond-shaped dependency is only
        # walked once.
        self._seen_ids: set[str] = set()
        self._walked_objects: set[str] = set()
        self._walked_steps: set[str] = set()

        self.total_seen = 0
        self.budget_exceeded = False

    # -- public API --------------------------------------------------

    @property
    def seen_ids(self) -> frozenset[str]:
        return frozenset(self._seen_ids)

    @property
    def node_count(self) -> int:
        return len(self._object_nodes) + len(self._step_nodes)

    def walk(self, target_id: str, explanation: dict[str, Any]) -> None:
        """Add *target_id* and everything ``explain_inference()`` found for it."""
        self._walk_object(target_id, explanation)

    def to_mermaid(self) -> str:
        alias: dict[str, str] = {}
        for i, node_id in enumerate((*self._object_nodes, *self._step_nodes)):
            alias[node_id] = f"n{i}"

        lines = ["graph TD"]
        for object_id, meta in self._object_nodes.items():
            label = self._object_label(object_id, meta["truncated"])
            lines.append(f'    {alias[object_id]}["{label}"]')
        for step_id, meta in self._step_nodes.items():
            label = self._step_label(step_id, meta)
            lines.append(f'    {alias[step_id]}{{"{label}"}}')
        for source, target, label, dashed in self._edges:
            src = alias.get(source)
            tgt = alias.get(target)
            if src is None or tgt is None:
                continue
            arrow = "-.->" if dashed else "-->"
            lines.append(f'    {src} {arrow}|"{label}"| {tgt}')
        return "\n".join(lines)

    # -- budget-aware node registration --------------------------------

    def _reserve(self, node_id: str) -> bool:
        """Count *node_id* towards ``total_seen`` once; report whether it fits the budget."""
        if node_id in self._seen_ids:
            return True
        self.total_seen += 1
        if len(self._seen_ids) >= self._max_objects:
            self.budget_exceeded = True
            return False
        self._seen_ids.add(node_id)
        return True

    def add_object(self, object_id: str, *, truncated: str | None) -> bool:
        if not self._reserve(object_id):
            return False
        if object_id not in self._object_nodes:
            self._object_nodes[object_id] = {"truncated": truncated}
        return True

    def add_step(self, step: dict[str, Any], *, superseded: bool) -> bool:
        step_id = step["step_id"]
        if not self._reserve(step_id):
            return False
        self._step_nodes[step_id] = {
            "operator": step.get("operator"),
            "confidence": step.get("confidence"),
            "superseded": superseded,
        }
        return True

    def add_edge(self, source: str, target: str, label: str, *, dashed: bool = False) -> None:
        key = (source, target, label, dashed)
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self._edges.append(key)

    # -- walking explain_inference()'s payload -------------------------

    def _walk_object(self, object_id: str, explanation: dict[str, Any]) -> bool:
        if not self.add_object(object_id, truncated=explanation.get("truncated")):
            return False
        if object_id in self._walked_objects:
            return True
        self._walked_objects.add(object_id)

        for step in explanation.get("active_steps") or []:
            self._walk_step(object_id, step)
        if self._include_superseded:
            for step in explanation.get("superseded_steps") or []:
                self._walk_superseded_step(object_id, step)
        return True

    def _walk_step(self, conclusion_id: str, step: dict[str, Any]) -> None:
        """Walk an *active* InferenceStep: recurse into its premises."""
        if not self.add_step(step, superseded=False):
            return
        step_id = step["step_id"]
        self.add_edge(step_id, conclusion_id, "concludes")

        if step_id in self._walked_steps:
            return
        self._walked_steps.add(step_id)

        for premise in step.get("premises") or []:
            if premise.get("cites_step"):
                self._cite_step(premise["object_id"], step_id)
                continue
            premise_id = premise["object_id"]
            if self._walk_object(premise_id, premise):
                self.add_edge(premise_id, step_id, "premise")

    def _walk_superseded_step(self, conclusion_id: str, step: dict[str, Any]) -> None:
        """
        Walk a *superseded* InferenceStep: a historical leaf record, not
        itself explorable further (``superseded_steps`` entries carry no
        ``premises`` -- see ``explain_inference``'s docstring).
        """
        if not self.add_step(step, superseded=True):
            return
        step_id = step["step_id"]
        self.add_edge(step_id, conclusion_id, "superseded", dashed=True)
        superseded_by = step.get("superseded_by")
        if superseded_by:
            self.add_edge(step_id, superseded_by, "superseded_by", dashed=True)

    def _cite_step(self, cited_step_id: str, citing_step_id: str) -> None:
        """
        Register a meta-reasoning citation (the premise names another
        ``InferenceStep``, not a conclusion -- see ``StalePremiseConstraint``).

        The cited step's own operator/confidence are only known if the
        walk also reaches it as a full active step elsewhere (it has its
        own conclusion, and gets a full ``add_step()`` call then, which
        upgrades this placeholder in place) -- never derived here.
        """
        if not self._reserve(cited_step_id):
            return
        if cited_step_id not in self._step_nodes:
            self._step_nodes[cited_step_id] = {
                "operator": None,
                "confidence": None,
                "superseded": False,
            }
        self.add_edge(cited_step_id, citing_step_id, "cites", dashed=True)

    # -- labels ----------------------------------------------------------

    def _object_label(self, object_id: str, truncated: str | None) -> str:
        obj = self._structure.get(object_id)
        base = f"{obj.identity.name} ({obj.identity.type})" if obj is not None else object_id
        base = base.replace('"', "#quot;")
        if truncated == "cycle":
            base += " [cycle]"
        elif truncated == "max_depth":
            base += " [truncated]"
        return base

    def _step_label(self, step_id: str, meta: dict[str, Any]) -> str:
        bits = []
        if meta["operator"]:
            bits.append(str(meta["operator"]))
        if meta["confidence"] is not None:
            bits.append(f"confidence {meta['confidence']}")
        label = ", ".join(bits) if bits else step_id
        if meta["superseded"]:
            label += " (superseded)"
        return label.replace('"', "#quot;")