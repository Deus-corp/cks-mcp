"""
Shared field-level diff helper for Knowledge Objects and Relations.

Used by both merge conflict reporting (tools/merge/handler.py) and
explain_diff (tools/explain_diff/handler.py), so "what changed about this
identity between two points in time" is computed and presented the same
way everywhere in cks-mcp, instead of two subtly-different
reimplementations drifting apart.
"""

from __future__ import annotations

from typing import Any


def field_level_diff(base_obj: Any, target_obj: Any) -> dict[str, Any]:
    """
    Generate a human-readable diff between two KnowledgeObjects (or
    CanonicalRelations, which are KnowledgeObjects) that share the same
    identity, at two different points in time -- e.g. a version being
    compared against the current session state, or one branch against
    the common ancestor in a merge conflict.

    Returns a dict with an ``action`` of:
      - ``added``    -- only `target_obj` exists (`base_obj` is None).
      - ``deleted``  -- only `base_obj` exists (`target_obj` is None).
      - ``modified`` -- both exist and at least one structure field
        (or, for a CanonicalRelation, its participants/relation_type,
        which live inside `structure`) differs.
      - ``unchanged`` -- both exist with byte-for-byte identical
        structure. This case matters to callers that see an identity
        pass through a remove+add cycle for reasons unrelated to its
        own content -- e.g. a relation cascade-relinked because one of
        its participants was replaced -- and need to tell that apart
        from a genuine edit to the relation itself.
    Returns ``{}`` if both are None (nothing to report).
    """
    if base_obj is None and target_obj is None:
        return {}
    if base_obj is None:
        return {
            "action": "added",
            "type": target_obj.identity.type,
            "name": target_obj.identity.name,
            "structure": dict(target_obj.structure),
        }
    if target_obj is None:
        return {
            "action": "deleted",
            "type": base_obj.identity.type,
            "name": base_obj.identity.name,
        }
    # Both exist — compute field-level changes.
    changes: dict[str, Any] = {}
    base_struct = dict(base_obj.structure)
    target_struct = dict(target_obj.structure)
    all_keys = set(base_struct) | set(target_struct)
    for key in sorted(all_keys):
        old_val = base_struct.get(key)
        new_val = target_struct.get(key)
        if old_val != new_val:
            changes[key] = {"from": old_val, "to": new_val}
    return {
        "action": "modified" if changes else "unchanged",
        "type": target_obj.identity.type,
        "name": target_obj.identity.name,
        "changes": changes,
    }
