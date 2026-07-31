# Verification & Integrity

The two tools behind `cks-mcp`'s anti-hallucination guarantees. See
[Security Model](../security.md) for the full trust model these implement.

## `verify_source`

Performs a **real HTTP request** against an external URL and builds a
cryptographically signed `VerificationRecord` from the actual result. This
is the **only** sanctioned way to produce a `VerificationRecord` — every
other tool treats a record without a valid signature as fabricated (see
below).

**Parameters:** `url` (string, required), `subject_id` (string, required —
the id of the Knowledge Object this verification is about).

**Response**

```json
{
  "objects": [
    {"identity": {"id": "vr-...", "type": "VerificationRecord", "name": "verification"},
     "structure": {"checked_at": "2026-07-30T12:00:00Z", "checked_via": "automated_http_check",
                   "http_status": 200, "signature": "<HMAC>"}},
    {"identity": {"id": "rel-...", "type": "Relation", "name": "r"},
     "structure": {"participants": ["<subject_id>", "vr-..."], "relation_type": "verified_by"}}
  ]
}
```

Merge this straight into your structure with `evolve_knowledge`
(`add_object` for both entries), or include it directly in a `json_data`
payload. The request itself is hardened against SSRF and DNS rebinding:
only `http`/`https` are allowed, the resolved IP is validated against
public-address ranges (blocking private, loopback, link-local, and
cloud-metadata ranges, plus CGNAT-style shared address space), and the
connection is pinned to the validated IP for the actual request — redirects
are followed manually, one hop at a time, re-validating each new target.

## `detect_contradictions`

Flags logical contradictions in a structure using two constraint types.
Read-only.

- **`mutual_exclusion`** — the same source–target pair has *both* of two
  declared relation types (e.g. both `supports` and `refutes`).
- **`functional_relation`** — a single source has *more than one* target via
  a relation type declared single-valued (e.g. a planet `orbits` two stars).

To use it, your structure must contain `MutualExclusionRule` and/or
`FunctionalRelationRule` objects declaring which relation types are subject
to which check:

```json
{"identity": {"id": "rule-1", "type": "MutualExclusionRule", "name": "no-support-and-refute"},
 "structure": {"relation_type_a": "supports", "relation_type_b": "refutes"}}
```

```json
{"identity": {"id": "rule-2", "type": "FunctionalRelationRule", "name": "single-orbit"},
 "structure": {"relation_type": "orbits"}}
```

**Parameters:** `session_id` or `json_data` (one of the two).

**Response**

```json
{
  "session_id": "sess-abc123",
  "contradiction_count": 1,
  "contradictions": [
    {"code": "CKS-EXT-FUNCTIONAL-RELATION", "severity": "warning", "source": "extension",
     "message": "...", "metadata": {}}
  ]
}
```

## Why provenance is checked *unconditionally*

A `VerificationRecord` looks the same to a downstream reader whether it was
genuinely produced by `verify_source` or hand-crafted by an LLM trying to
look convincing. Because of that, `validate_knowledge`, `evolve_knowledge`,
`merge_knowledge`, `merge_branch`, and the `json_data` fallback paths of
`serialize_knowledge`/`explain_knowledge`/`detect_contradictions` all check
every `VerificationRecord`'s HMAC signature **regardless of whether you
requested the `verification_record` extension**. A forged record can never
become a persisted, readable version — see [Security Model](../security.md).
