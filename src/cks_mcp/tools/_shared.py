"""
Shared, reusable pieces of tool description/schema text.

Kept separate so multiple tools/*/schema.py modules can reference the
same wording (e.g. how a Knowledge Structure JSON string is shaped)
without duplicating long descriptive text in each one.
"""

from __future__ import annotations

JSON_DATA_DESCRIPTION = (
    "A valid CKS Knowledge Structure as a JSON string. Each object has "
    "an 'identity' ({'id', 'type', 'name'}) and a free-form 'structure' "
    "dict. Relations are objects whose 'structure' contains "
    "'participants' (a list of object ids) and 'relation_type'. Example: "
    '\'{"objects": [{"identity": {"id": "obj-1", "type": "Definition", '
    '"name": "Photosynthesis"}, "structure": {"content": "..."}}, '
    '{"identity": {"id": "rel-1", "type": "Relation", "name": "r"}, '
    '"structure": {"participants": ["obj-1", "obj-2"], "relation_type": '
    "'derives\"}}]}'."
)

CONTRADICTION_RULE_EXAMPLES = (
    "Examples of contradiction rules:\n"
    '- MutualExclusionRule: {"identity": {"id": "rule-1", "type": "MutualExclusionRule", "name": "no-support-and-refute"}, '
    '"structure": {"relation_type_a": "supports", "relation_type_b": "refutes"}}. '
    "This flags when the SAME source-target pair has BOTH a 'supports' and a 'refutes' relation.\n"
    '- FunctionalRelationRule: {"identity": {"id": "rule-2", "type": "FunctionalRelationRule", "name": "single-orbit"}, '
    '"structure": {"relation_type": "orbits"}}. '
    "This flags when a single source has MORE THAN ONE target via 'orbits'."
)
