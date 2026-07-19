import requests
from datetime import datetime, timezone
from typing import Any
from cks_runtime.runtime import Runtime

def verify_source(runtime: Runtime, arguments: dict[str, Any]) -> dict[str, Any]:
    url = arguments["url"]
    subject_id = arguments["subject_id"]

    try:
        resp = requests.head(url, timeout=5, allow_redirects=True)
        status = resp.status_code
    except Exception:
        status = 0

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    record = {
        "objects": [
            {
                "identity": {"id": "vr-1", "type": "VerificationRecord", "name": "verification"},
                "structure": {
                    "checked_at": timestamp,
                    "checked_via": "automated_http_check",
                    "http_status": status,
                },
            },
            {
                "identity": {"id": "rel-1", "type": "Relation", "name": "r"},
                "structure": {
                    "participants": [subject_id, "vr-1"],
                    "relation_type": "verified_by",
                },
            },
        ]
    }
    return record