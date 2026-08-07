import json
import os
import subprocess
import sys

if len(sys.argv) < 2:
    print("usage: python create_fork.py <session_id> [db_path]", file=sys.stderr)
    sys.exit(1)

session_id = sys.argv[1]
db_path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/cks-b.db"

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
        "CKS_GOSSIP_ENABLED": "true",
        "CKS_GOSSIP_PORT": "8766",
        "CKS_GOSSIP_PEERS": "localhost:8765",
        "CKS_GOSSIP_HOST": "127.0.0.1",
    }
)

proc.stdin.write(json.dumps(request) + "\n")
proc.stdin.flush()

response_line = proc.stdout.readline()
proc.terminate()

response = json.loads(response_line)
print(json.dumps(response, indent=2))