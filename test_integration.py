import subprocess, json, sys

def test_validate_via_server():
    # запускаем сервер
    proc = subprocess.Popen(
        [sys.executable, "-m", "cks_mcp.server"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "validate_knowledge",
            "arguments": {
                "json_data": '{"objects":[{"identity":{"id":"obj-1","type":"Definition","name":"Test"},"structure":{}}]}'
            }
        }
    }
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()
    response = json.loads(proc.stdout.readline())
    proc.terminate()

    assert "result" in response, f"Expected result, got {response}"
    content = json.loads(response["result"]["content"][0]["text"])
    assert content["valid"] == True
    assert "version_id" in content
    assert "session_id" in content
    print("Integration test PASSED")

if __name__ == "__main__":
    test_validate_via_server()