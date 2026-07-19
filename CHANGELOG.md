# Changelog


---

## [0.7.8] - 2026-07-19

### Fixed
- `list_versions` now builds version history directly from the session instead of delegating to the OperationExecutor, fixing the persistent error that prevented LLMs from inspecting session history.

---

## [0.7.7] - 2026-07-19

### Added
- **Session-aware tools:** `validate_knowledge`, `serialize_knowledge`, `explain_knowledge`, and `evolve_knowledge` now accept an optional `session_id` parameter to operate on an existing session instead of creating a new one. This enables predictable, multi-step workflows within a single session.
- `revert_version` now returns the `serialized` canonical JSON of the reverted state, eliminating the need for a separate `serialize_knowledge` call to verify the result.
- **Production-ready provenance:** The signing secret can now be configured via the `CKS_MCP_SECRET` environment variable (supports raw strings, hex, and base64), making provenance verification stable across server restarts.
- Improved error handling in `list_versions`.

### Changed
- `evolve_knowledge` no longer requires `json_data` when `session_id` is provided, reducing unnecessary re-parsing of large structures.
- Provenance checks now distinguish between ambiguous, unlinked, and unverified records for clearer diagnostics.

---

## [0.7.6] - 2026-07-19

### Fixed
- `list_versions` now handles internal errors gracefully and returns an empty list when no versions exist, instead of failing silently.

---

## [0.7.5] - 2026-07-19

### Added
- `evolve_knowledge` now accepts an optional `session_id` parameter. When provided, the evolution is applied to the existing session, adding a new version to its history. This enables predictable version tracking within a single session.

---

## [0.7.4] - 2026-07-19

### Changed
- Improved tool descriptions for `validate_knowledge`, `evolve_knowledge`, `list_versions`, and `revert_version` to explicitly document the session and versioning workflow, helping LLMs discover the correct usage pattern without trial and error.

---

## [0.7.3] - 2026-07-19

### Fixed
- `list_versions` and `revert_version` now require an explicit `session_id` parameter, eliminating unpredictable behaviour when multiple sessions exist. Tools always return the `session_id` they operated on.

---

## [0.7.2] - 2026-07-19

### Fixed
- Response format now matches the incoming request: `Content-Length`-framed for clients that use headers, plain line-delimited for legacy clients. This restores full compatibility with Claude Desktop and other MCP clients.

---

## [0.7.1] - 2026-07-19

### Fixed
- Server now supports both `Content-Length`‑framed and plain line‑delimited modes, restoring compatibility with Claude Desktop and other MCP clients that do not use headers.

---

## [0.7.0] - 2026-07-19

### Added
- `list_versions` and `revert_version` tools, giving LLMs the ability to inspect the version history of a session and safely roll back to any previous state. Powered by `cks-runtime`'s new `ListVersionsOperation` and `RevertVersionOperation`.

---

## [0.6.3] - 2026-07-19

### Fixed
- **HTTPS/SNI fix in `verify_source`**: Replaced custom HTTPAdapter with thread-local `socket.getaddrinfo` override, preserving SNI and SSL certificate validation while still preventing DNS rebinding.
- **MCP protocol compliance**: Implemented `Content-Length` header-based message framing, fixing potential JSON parsing errors for large or formatted requests.
- **LLM-friendly errors**: Business errors are now returned as successful tool responses with `isError: true`, allowing LLMs to read and recover from errors instead of treating them as server crashes.

---

## [0.6.2] - 2026-07-19

### Fixed
- Provenance check is now unconditional for any `VerificationRecord`, closing a bypass where an LLM could skip validation by omitting the extension parameter.
- DNS rebinding SSRF vector closed by pinning HTTP connections to the specific IP address resolved during the safety check.

---

## [0.6.1] - 2026-07-19

### Fixed
- Restored standard MCP protocol version (`2024-11-05`) that was accidentally overwritten, which prevented Claude Desktop from connecting.

---

## [0.6.0] - 2026-07-19

### Added
- Provenance signing for `VerificationRecord` – only records produced by `verify_source` pass the new `CKS-MCP-UNVERIFIED-PROVENANCE` check.
- SSRF protection in `verify_source` – URLs are validated against public-IP allowlist.
- Unique IDs (uuid4) for all objects created by `verify_source`.
- Tests for SSRF protection, unique IDs, and provenance signing (7 new tests, total 24 passed).

### Changed
- All tools now catch `cks.SerializationError` and return structured error messages instead of raw tracebacks.
- `invalid_json_error` now accepts a `details` parameter.

---

## [0.5.2] - 2026-07-19

### Changed
- Improved error responses in MCP server: structured error messages with types (`invalid_json`, `validation_failed`) now replace raw tracebacks, helping LLMs understand what went wrong and how to recover.
- Updated server version string to 0.5.2 and imported new error helpers from `cks_mcp.errors`.

---

## [0.5.1] - 2026-07-19

### Changed
- `serialize_knowledge` and `explain_knowledge` tools now read operation results directly from the transaction's `results` field instead of calling `CoreBridge` a second time. This eliminates redundant semantic computations and keeps all operation payloads in one place.

---

## [0.5.0] - 2026-07-19

### Added
- New `verify_source` tool. It performs an actual HTTP request to check a source's availability and creates a `VerificationRecord` object. This ensures that verification records can only be produced by real checks, not fabricated by the model.

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