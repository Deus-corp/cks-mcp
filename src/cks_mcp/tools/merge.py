"""
merge_knowledge: three-way merge of Knowledge Structures.
"""

from typing import Any
import cks
from cks_runtime.runtime import Runtime

def merge_knowledge(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Perform a three-way merge.

    Expects:
        json_data_base, json_data_branch_a, json_data_branch_b
    Returns the merged structure or a structured conflict report.
    """
    try:
        base = cks.parse(arguments["json_data_base"])
        branch_a = cks.parse(arguments["json_data_branch_a"])
        branch_b = cks.parse(arguments["json_data_branch_b"])
        merged = base.merge(branch_a, branch_b)
        serialized = runtime.core_bridge.serialize(merged)
        return {
            "merged": True,
            "serialized": serialized,
        }
    except Exception as e:
        # Check if this is a merge conflict error by duck-typing
        if hasattr(e, 'conflicts'):
            return {
                "merged": False,
                "conflicts": [
                    {
                        "object_id": c.object_id,
                        "base": str(c.base) if c.base else None,
                        "branch_a": str(c.branch_a) if c.branch_a else None,
                        "branch_b": str(c.branch_b) if c.branch_b else None,
                    }
                    for c in e.conflicts
                ],
            }
        return {"error": str(e)}