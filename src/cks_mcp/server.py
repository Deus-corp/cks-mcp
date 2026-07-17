"""
CKS MCP Server – JSON-RPC over stdio.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from cks_runtime.runtime import Runtime
from cks_runtime_plugins.cks_core import CksCoreAdapter

from cks_mcp.tools import (
    validate_knowledge,
    serialize_knowledge,
    explain_knowledge,
    evolve_knowledge,
)

TOOLS = {
    "validate_knowledge": validate_knowledge,
    "serialize_knowledge": serialize_knowledge,
    "explain_knowledge": explain_knowledge,
    "evolve_knowledge": evolve_knowledge,
}

def handle_request(runtime: Runtime, request: dict[str, Any]) -> dict[str, Any]:
    method = request.get("method")
    params = request.get("params", {})
    if method == "tools/list":
        return {
            "tools": [
                {
                    "name": name,
                    "description": "",
                    "inputSchema": {"type": "object", "properties": {"json_data": {"type": "string"}}},
                }
                for name in TOOLS
            ]
        }
    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if tool_name not in TOOLS:
            return {"error": f"Unknown tool: {tool_name}"}
        try:
            result = TOOLS[tool_name](runtime, arguments)
            return {"result": result}
        except Exception as e:
            return {"error": str(e)}
    return {"error": "Unsupported method"}

def main() -> None:
    runtime = Runtime(core=CksCoreAdapter())
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(runtime, request)
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps({"error": "Invalid JSON"}) + "\n")
            sys.stdout.flush()

if __name__ == "__main__":
    main()