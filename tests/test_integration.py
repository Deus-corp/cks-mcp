"""
Real subprocess integration tests: spins up `python -m cks_mcp.server`
as an actual child process and talks JSON-RPC over its real stdin/
stdout, instead of calling handle_request() in-process.

This is the only place in the test suite that exercises the actual
transport boundary (process framing, stdout buffering, process
lifecycle) rather than pure Python function calls -- it was
accidentally dropped in the commit that added the `extensions`
parameter to validate_knowledge (v0.4.0) and is restored here, with
a second case covering that new parameter specifically, since that
is exactly the kind of thing an in-process unit test cannot catch.
"""

import json
import subprocess
import sys


def _call(request: dict) -> dict:
    proc = subprocess.Popen(
        [sys.executable, "-m", "cks_mcp.server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    assert line, f"Server produced no output on stdout (stderr: {proc.stderr.read()})"
    return json.loads(line)


def test_validate_via_server():
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "validate_knowledge",
            "arguments": {
                "json_data": (
                    '{"objects":[{"identity":{"id":"obj-1","type":"Definition",'
                    '"name":"Test"},"structure":{}}]}'
                )
            },
        },
    }
    response = _call(request)

    assert "result" in response, f"Expected result, got {response}"
    content = json.loads(response["result"]["content"][0]["text"])
    assert content["valid"] is True
    assert "version_id" in content
    assert "session_id" in content


def test_validate_with_extensions_via_server():
    """
    The anti-hallucination-citation scenario, over the real subprocess
    transport: an EmbeddingProjection 'represents' relation pointing
    at an object id that does not exist in the structure.
    """
    structure = {
        "objects": [
            {
                "identity": {"id": "src-1", "type": "Document", "name": "Real"},
                "structure": {},
            },
            {
                "identity": {"id": "claim-1", "type": "EmbeddingProjection", "name": "c"},
                "structure": {"store_ref": "vecdb://x"},
            },
            {
                "identity": {"id": "rel-1", "type": "Relation", "name": "r"},
                "structure": {
                    "participants": ["ghost-id", "claim-1"],
                    "relation_type": "represents",
                },
            },
        ]
    }
    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "validate_knowledge",
            "arguments": {
                "json_data": json.dumps(structure),
                "extensions": ["embedding_projection"],
            },
        },
    }
    response = _call(request)

    assert "result" in response, f"Expected result, got {response}"
    content = json.loads(response["result"]["content"][0]["text"])
    assert content["valid"] is False
    assert content["extensions_applied"] == ["embedding_projection"]
    codes = {d["code"] for d in content["diagnostics"]}
    assert "CKS-EXT-EMBEDDING-PROJECTION" in codes


def test_validate_unknown_extension_via_server():
    request = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "validate_knowledge",
            "arguments": {
                "json_data": '{"objects":[]}',
                "extensions": ["not_a_real_extension"],
            },
        },
    }
    response = _call(request)

    assert "result" in response, f"Expected result, got {response}"
    content = json.loads(response["result"]["content"][0]["text"])
    assert content["error"] == "unknown_extension"


if __name__ == "__main__":
    test_validate_via_server()
    test_validate_with_extensions_via_server()
    test_validate_unknown_extension_via_server()
    print("Integration tests PASSED")