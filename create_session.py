import json
import os
import subprocess

request = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
        "name": "validate_knowledge",
        "arguments": {
            "json_data": json.dumps({
                "objects": [
                    {
                        "identity": {
                            "id": "concept-1",
                            "type": "Concept",
                            "name": "Test Concept"
                        },
                        "structure": {"description": "Initial version"}
                    }
                ]
            })
        }
    }
}

proc = subprocess.Popen(
    ["cks-mcp"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True,
    env={
        **os.environ,
        "CKS_MCP_DB_PATH": "/tmp/cks-a.db",
        "CKS_GOSSIP_ENABLED": "true",
        "CKS_GOSSIP_PORT": "8765",
        "CKS_GOSSIP_PEERS": "localhost:8766",
        "CKS_GOSSIP_HOST": "127.0.0.1",
    }
)

proc.stdin.write(json.dumps(request) + "\n")
proc.stdin.flush()

response_line = proc.stdout.readline()
proc.terminate()

response = json.loads(response_line)
print("Full response:", json.dumps(response, indent=2))

if "result" in response:
    result_text = response["result"]["content"][0]["text"]
    result_json = json.loads(result_text)
    print("session_id:", result_json.get("session_id"))