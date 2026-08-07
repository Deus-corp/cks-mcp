import json
import os
import sys
import subprocess

if len(sys.argv) < 2:
    print("usage: python create_fork.py <session_id> [db_path]", file=sys.stderr)
    sys.exit(1)

session_id = sys.argv[1]
db_path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/cks-b/cks.db"

request = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
        "name": "evolve_knowledge",
        "arguments": {
            "session_id": session_id,
            "operations": [
                {
                    "type": "update_object",
                    "object_id": "concept-1",
                    "structure_patch": {"description": "Version from instance B"}
                }
            ]
        }
    }
}

proc = subprocess.Popen(
    ["cks-mcp"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True,
    env={
        **os.environ,
        "CKS_MCP_DB_PATH": db_path,
        # Gossip disabled for the same reason as in create_session.py:
        # this one-shot subprocess only needs to write into db_path, and
        # hardcoding CKS_GOSSIP_PORT=8766 collided with the long-lived
        # server B already listening on that port.
        "CKS_GOSSIP_ENABLED": "false",
    }
)

proc.stdin.write(json.dumps(request) + "\n")
proc.stdin.flush()

response_line = proc.stdout.readline()
proc.terminate()
stderr_output = proc.stderr.read()

if not response_line:
    print("No response from cks-mcp subprocess. stderr:", file=sys.stderr)
    print(stderr_output, file=sys.stderr)
    sys.exit(1)

response = json.loads(response_line)
print(json.dumps(response, indent=2))
if "error" in response or "error" in response.get("result", {}).get("content", [{}])[0].get("text", ""):
    if stderr_output.strip():
        print("--- subprocess stderr ---", file=sys.stderr)
        print(stderr_output, file=sys.stderr)