# Changelog


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