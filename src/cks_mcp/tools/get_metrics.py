"""
get_metrics: return the current runtime metrics snapshot.
"""

from typing import Any
from cks_runtime.runtime import Runtime


def get_metrics(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    """Return the current metrics snapshot from the runtime."""
    return {
        "metrics": runtime.metrics.snapshot(),
    }