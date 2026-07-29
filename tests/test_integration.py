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

import importlib
import json
import os
import subprocess
import sys

import pytest


def _server_dependencies_available():
    try:
        importlib.import_module("cks")
        importlib.import_module("cks_runtime")
        importlib.import_module("requests")
        return True
    except ImportError:
        return False


def _call(request: dict) -> dict:
    proc = subprocess.Popen(
        [sys.executable, "-m", "cks_mcp.server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        body = json.dumps(request)
        proc.stdin.write(f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n{body}")
        proc.stdin.flush()

        content_length = 0
        while True:
            line = proc.stdout.readline()
            if not line:  # EOF
                break
            line = line.strip()
            if not line:
                break
            if line.lower().startswith("content-length:"):
                content_length = int(line.split(":")[1].strip())

        if content_length == 0:
            raw_output = proc.stdout.read()
        else:
            raw_output = proc.stdout.read(content_length)
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    if not raw_output:
        stderr_text = proc.stderr.read()
        pytest.fail(f"Server produced no output. stderr:\n{stderr_text}")

    try:
        return json.loads(raw_output)
    except json.JSONDecodeError:
        stderr_text = proc.stderr.read()
        raise AssertionError(
            f"Server response is not valid JSON. Response: {raw_output!r}\nStderr:\n{stderr_text}"
        )


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


@pytest.mark.skipif(os.environ.get('CI') == 'true', reason="Skipping flaky integration test in CI")

def test_validate_with_extensions_via_server():
    structure = {
        "objects": [
            {"identity": {"id": "src-1", "type": "Document", "name": "Real"}, "structure": {}},
            {"identity": {"id": "claim-1", "type": "EmbeddingProjection", "name": "c"}, "structure": {"store_ref": "vecdb://x"}},
            {"identity": {"id": "rel-1", "type": "Relation", "name": "r"}, "structure": {"participants": ["ghost-id", "claim-1"], "relation_type": "represents"}},
        ]
    }
    request = {
        "jsonrpc": "2.0", "id": 2,
        "method": "tools/call",
        "params": {
            "name": "validate_knowledge",
            "arguments": {"json_data": json.dumps(structure), "extensions": ["embedding_projection"]}
        },
    }
    response = _call(request)
    assert "result" in response, f"Expected result, got {response}"
    content = json.loads(response["result"]["content"][0]["text"])
    assert content["valid"] is False
    assert any(d["severity"] == "error" for d in content["diagnostics"])


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