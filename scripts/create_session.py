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

db_path = os.environ.get("CKS_MCP_DB_PATH", "/tmp/cks-a/cks.db")

proc = subprocess.Popen(
    ["cks-mcp"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True,
    env={
        **os.environ,
        "CKS_MCP_DB_PATH": db_path,
        # Gossip deliberately left disabled here: this is a one-shot
        # subprocess that just needs to write a session into db_path.
        # Hardcoding CKS_GOSSIP_PORT=8765 previously collided with the
        # already-running long-lived server A listening on that same
        # port, causing a silent bind failure (stderr wasn't printed).
        "CKS_GOSSIP_ENABLED": "false",
    }
)

proc.stdin.write(json.dumps(request) + "\n")
proc.stdin.flush()

response_line = proc.stdout.readline()
proc.terminate()
stderr_output = proc.stderr.read()

if not response_line:
    print("No response from cks-mcp subprocess. stderr:")
    print(stderr_output)
    raise SystemExit(1)

response = json.loads(response_line)
print("Full response:", json.dumps(response, indent=2))

if "result" in response:
    result_text = response["result"]["content"][0]["text"]
    result_json = json.loads(result_text)
    print("session_id:", result_json.get("session_id"))