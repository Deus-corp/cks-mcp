# Changelog


---

## [0.4.4] - 2026-07-19

### Added
- `verification_record` extension now available in `validate_knowledge`'s `extensions` parameter. This extension checks the integrity of `VerificationRecord` objects, ensuring they have exactly one `verified_by` relation, a valid timestamp, a recognized check method, and no qualitative judgment fields.
- Updated tool descriptions with an example of a correct `VerificationRecord`.

---

## [0.4.3] - 2026-07-19

### Changed
- Added a complete worked example of a correct `EmbeddingProjection` with its `represents` relation to the description of the `extensions` parameter in `validate_knowledge`. This further reduces trial-and-error by giving the model a template to follow.

---

## [0.4.2] - 2026-07-19

### Changed
- Improved tool descriptions: `json_data` now includes a full worked example of a CKS Knowledge Structure, and `operations` in `evolve_knowledge` includes per‑operator field requirements and an example. This dramatically reduces the number of trial‑and‑error round‑trips a cold LLM needs to construct valid requests (measured: from 3 to 0).

---

## [0.4.1] - 2026-07-18

### Added
- Restored and expanded subprocess integration tests (`test_integration.py`) covering real stdin/stdout transport, including the new `extensions` parameter (3 new tests, total 19 passed).

---

## [0.4.0] - 2026-07-18

### Added
- `validate_knowledge` now supports an optional `extensions` parameter (list of human-readable names like `"embedding_projection"`) to opt into additional validation rules for a single call.
- Structured error response for unknown extension names instead of a raw traceback.
- Integration tests for the extensions feature with real Runtime + CksCoreAdapter (5 new tests, total 17 passed).

### Changed
- Updated `validate_knowledge` tool description in MCP server schema to document the `extensions` parameter.

---

## [0.3.3] - 2026-07-18

### Removed
- Deleted obsolete `src/cks_mcp/tools.py` – an outdated copy of test utilities that survived four releases.

---

## [0.3.2] - 2026-07-18

### Fixed
- `validate_knowledge` now correctly returns `"valid": false` with structured diagnostics when a Knowledge Structure is invalid, instead of crashing or hardcoding `true`. It reads diagnostics from the session after the validation transaction (bugs #1, #2).
- Updated tests to cover both valid and invalid structure scenarios.

---

## [0.3.1] - 2026-07-18

### Fixed
- `evolve_knowledge` now uses `cks.evolution.parse_operations` to convert JSON operation descriptors into proper `StructuralOperator` objects, fixing the `AttributeError: 'dict' object has no attribute 'apply'` crash.
- Requires `cks-runtime>=0.4.4` and `cks-core>=1.2.1`.
- Added missing `EvolveOperation` import in `evolve_knowledge` tool.

### Changed
- Updated tests to use valid JSON operation descriptors for evolve.

---

## [0.3.0] - 2026-07-18

### Changed
- Tools now use the full `create_session` → `begin_transaction` → `commit_transaction` cycle from `cks-runtime`. Every call produces an immutable Version and collects Diagnostics.
- Requires `cks-runtime>=0.4.2` and `cks-core>=1.2.0`.
- Responses now include `version_id` and `session_id` for traceability.

### Fixed
- `test_server.py` now uses serializable mocks for session and version, eliminating `Object of type MagicMock is not JSON serializable` errors.

### Updated
- README reflects transactional tool behaviour and new response fields.

---

## [0.2.1] - 2026-07-18

### Changed
- Improved tool responses for better LLM readability.
  - `validate_knowledge` now returns `error_count`, `warning_count`, `information_count` and a human‑readable message.
  - `explain_knowledge` now returns `object_count`, `relation_count` and a summary.
  - `evolve_knowledge` returns `serialized` result and `operations_applied` count.
- Updated tests to verify new response fields (11 passing).

---

## [0.2.0] - 2026-07-18

### Added
- Working MCP server with four tools: `validate_knowledge`, `serialize_knowledge`, `explain_knowledge`, `evolve_knowledge`.
- LLM client (`llm_client/cks_llm_client.py`) supporting Groq, DeepSeek, and local llama_cpp models.
- `.env` support via `python-dotenv`.
- Unit tests for server and tools (9 passing).

### Changed
- Tools now use direct `CoreBridge` calls instead of sessions/transactions (avoids serialization issues).
- Server reads JSON-RPC requests line-by-line from stdin and writes responses to stdout.

### Fixed
- `cannot pickle 'mappingproxy' object` error resolved by using `CoreBridge` directly.
- Valid Knowledge Structure JSON examples added to tests.

---

## [0.1.1] - 2026-07-15

### Fixed

- CI/CD publish workflow trigger.

---

## [0.1.0] - 2026-07-15

### Added

- Initial MCP server implementation with JSON-RPC over stdio.
- `validate_knowledge` tool.
- `query_relations` tool.
- `compare_structures` tool.
- `evolve_knowledge` tool.
- `derive_knowledge` tool.
- CI/CD pipeline (GitHub Actions).
- 20 tests passing.