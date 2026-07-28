# Changelog


---

## [1.12.0] - 2026-07-28

### Added
- **`detect_contradictions` tool** — surfaces mutual exclusion and functional relation violations using the new contradiction constraints from cks-core.
- **`fork_sandbox` tool** — creates an isolated branch, optionally applies a hypothesis, and shows a diff from the fork point, all without affecting the parent session.

---

## [1.11.1] - 2026-07-28

### Added
- `validate_knowledge` now supports `mutual_exclusion` and `functional_relation` extensions for contradiction detection.
- Bumped `cks-runtime` dependency to `>=1.20.2` and `cks-core` to `>=1.13.0`.

---

## [1.11.0] - 2026-07-28

### Added
- `suggest_evolution` now accepts an optional `operations` parameter: when
  provided, it dry-runs those candidate operations against the session
  (the same non-committing path `evolve_knowledge` uses internally) and
  returns `would_apply`/`diagnostics`/`preview_serialized` instead of the
  template/guidance response. Lets a caller check a concrete operations
  list before spending a real `evolve_knowledge` call — and a real
  version — on a guess. Fully backward compatible: omitting `operations`
  returns the same template response as before.

---

## [1.10.6] - 2026-07-28

### Changed
- Bumped `cks-runtime` dependency to `>=1.20.1` (production stable status, `cks-core>=1.12.1` compatibility).
- Bumped `cks-core` dependency to `>=1.12.1` (fix for truncated `schema.py`).
- All three ecosystem packages now aligned on stable releases.

---

## [1.10.5] - 2026-07-28

### Changed
- Bumped `cks-runtime` dependency to `>=1.20.0` (VersionVector and fast-path merge, ADR-007 Part 2). `merge_branch` and `merge_knowledge` automatically benefit from no-op and fast-forward detection.

---

## [1.10.4] - 2026-07-28

### Changed
- Bumped `cks-runtime` dependency to `>=1.19.0` (indexed and vectorized embeddings, full mypy compliance, selective strict mode).

---

## [1.10.2] - 2026-07-27

### Changed
- Added `ruff` linting and `mypy` type checking to CI pipeline.
- Moved demo GIF to external hosting (GitHub Releases), reducing repository clone size by 6.7 MB.

---

## [1.10.1] - 2026-07-27

### Added
- `search_semantic` now supports an optional `min_score` parameter to filter results by minimum cosine similarity threshold. Results below the threshold are excluded, and an empty result set triggers a clear "nothing relevant found" message.

---

## [1.10.0] - 2026-07-27

### Added
- **`export_knowledge` tool** — export a session's Knowledge Structure to JSON-LD, Turtle, or RDF/XML, leveraging cks-core's built-in RDF/JSON-LD adapters.
- This is the 19th tool in the cks-mcp suite.

### Fixed
- `suggest_evolution` description in README and tool schema now accurately reflects its current behaviour.
- Updated MCP protocol version from `2024-11-05` to `2025-11-25`.
- Removed dead reference to non-existent `llm_client/cks_llm_client.py` from README.

---

## [1.9.3] - 2026-07-27

### Fixed
- `suggest_evolution` description in README and tool schema now accurately reflects its current behaviour (state inspection + guidance), removing promises of non-existent AI-generated operations and dry-run validation.
- Updated MCP protocol version from `2024-11-05` to `2025-11-25`.
- Removed dead reference to non-existent `llm_client/cks_llm_client.py` from README.

---

## [1.9.2] - 2026-07-27

### Fixed
- `visualize_graph` now returns `total_found_nodes`, `returned_nodes`, and `is_truncated` metadata, matching the contract of other subgraph tools.
- `max_objects` is now enforced consistently in both branches (with and without `seed_ids`), using `query_subgraph` with compact mode for all cases.
- Replaced `hasattr` duck-typing with `isinstance` for relation detection, matching the rest of the codebase.

---

## [1.9.1] - 2026-07-27

### Fixed
- `visualize_graph` now generates valid Mermaid syntax for all node IDs, including those with special characters.
- `explain_diff` now correctly distinguishes modified objects from add/remove pairs, and reports cascade-relinked relations as "relinked" rather than falsely claiming they were deleted and re-added.
- `suggest_evolution` now uses `isinstance(obj, CanonicalRelation)` instead of fragile `hasattr` duck-typing.

### Changed
- Extracted shared `field_level_diff` helper into new `cks_mcp.diffing` module, used by both merge tools and `explain_diff`.
- Extracted `TOOLS` registry into new `cks_mcp.tool_registry` module, reducing `server.py` from 929 to 322 lines.
- Added 6 functional end-to-end tests for the three new tools.

---

## [1.9.0] - 2026-07-27

### Added
- **`visualize_graph`** tool — exports a subgraph in Mermaid format for native rendering in Claude Desktop.
- **`explain_diff`** tool — produces a natural-language explanation of changes between two versions, complementing `compare_versions`.
- **`suggest_evolution`** tool — accepts a textual description of a desired change and returns a proposed list of valid evolution operators with a dry-run validation, without committing.
- 3 new tests covering the new tools' parameter validation.

### Changed
- `validate_knowledge` now supports `type_hierarchy` and `relation_type` extensions.
- Bumped `cks-runtime` to `>=1.18.2` and `cks-core` to `>=1.12.0`.

---

## [1.8.2] - 2026-07-27

### Added
- `validate_knowledge` now supports `type_hierarchy` and `relation_type` extensions, enabling ontology-based type checking and relation validation.
- Bumped `cks-runtime` to `>=1.18.2` and `cks-core` to `>=1.12.0`.

---

## [1.8.1] - 2026-07-27

### Changed
- Bumped `cks-runtime` to `>=1.18.1` (proper rollback with state restoration, DispatchRequest state mutation) and `cks-core` to `>=1.11.4` (UpdateObject export, iterative DFS, compose batching, CLI fixes, frozen metadata).

---

## [1.8.0] - 2026-07-27

### Changed
- **Breaking:** `revert_version` and `list_versions` now return the same structured `{"error": "<code>", "message": "<text>"}` shape as every other tool, instead of ad-hoc human sentences.
- `search_semantic` no longer silently swallows exceptions raised during vector search. The `not_found` response's `message` now includes the underlying error when one occurred.

### Added
- New `internal_error()` helper in `cks_mcp.errors`.
- New tests: `tests/test_revert.py` (9 tests) and `tests/test_search_semantic.py` (12 tests), including real end-to-end vector-search tests against a `SQLiteStorage`-backed `Runtime`.
- `search_semantic` now rejects an empty query immediately.
- `search_semantic` now includes a `scores` field in successful responses.

---

## [1.7.14] - 2026-07-26

### Added
- `search_semantic` now rejects an empty or whitespace-only `query` immediately with a clear `empty_query` error, instead of proceeding to (pointlessly) embed and vector-search on it.
- `search_semantic` now includes a `scores` field in successful responses when seeds were found via vector search — a dict mapping each matched seed `object_id` to its similarity score, to help debug strong vs. weak matches. Omitted when `seed_ids` were supplied explicitly, since there's no similarity score to report for those.

### Changed
- Bumped `cks-runtime` dependency to `>=1.17.7` (`search_embeddings` now returns `(object_id, similarity_score)` pairs instead of bare object IDs; `search_semantic` has been updated to consume the new return type).

---

## [1.7.13] - 2026-07-26

### Changed
- Bumped `cks-runtime` dependency to `>=1.17.5` (fixes `OutboxEmbeddingWorker` JSON payload parsing, enabling embedding generation for semantic search).

---

## [1.7.12] - 2026-07-26

### Added
- `server.py` now loads environment variables from `~/.cks-mcp/.env` at startup, ensuring `HF_TOKEN` (and any future configuration) persists across restarts and is always available to the embedding client.
- Removed old `src/cks_mcp/.env` and `src/cks_mcp/.env_example` in favour of the stable `~/.cks-mcp/` directory.

---

## [1.7.11] - 2026-07-26

### Changed
- Bumped `cks-runtime` to `>=1.17.4` (embedding dimension mismatch safety, proper `embedding_client` wiring) and `cks-core` to `>=1.11.2` (merge resolutions validation fix).

---

## [1.7.10] - 2026-07-26

### Fixed
- `search_semantic` now uses `runtime.embedding_client` (the same client instance used for indexing) instead of falling back to `StubEmbeddingClient`, restoring real semantic search functionality.

---

## [1.7.9] - 2026-07-26

### Fixed
- **Thread-safe DNS rebinding protection:** `verify_source`'s `pin_dns` context manager now uses reference-counted activation to prevent a race condition where a concurrent request could disable the DNS pinning for another in-flight request.
- **`Runtime` now properly stores and exposes `embedding_client`:** `search_semantic` was silently falling back to `StubEmbeddingClient` for query encoding, returning irrelevant results. Now uses the same client configured for indexing.
- **Embedding dimension mismatch detection:** `search_embeddings` now safely skips stored embeddings whose dimension differs from the query, instead of silently computing garbage similarity scores.
- **`KnowledgeStructure.merge()` contract fix:** a `resolutions` entry for an id that both branches touched but converged on the same value is now correctly rejected with `ValueError`, as documented.
- **Stable data directory:** provenance secret and SQLite database are now stored under `~/.cks-mcp` (overridable via `CKS_MCP_DATA_DIR`), so server restarts from different working directories no longer lose previously signed verifications or create empty databases.

---

## [1.7.8] - 2026-07-26

### Fixed
- **Critical provenance bypass:** `verify_structure_provenance` now identifies `verified_by` relations structurally (via `structure.relations()`), not by the caller-chosen `identity.type` string. Previously, a forged `VerificationRecord` linked by a relation with any `identity.type` other than the literal string `"Relation"` was invisible to the signature check and could be committed as a valid version.
- Added 2 regression tests confirming forged records are rejected and genuine records are accepted regardless of `identity.type`.
- Bumped `cks-runtime` to `>=1.17.3` and `cks-core` to `>=1.11.1`.

---

## [1.7.7] - 2026-07-26

### Fixed
- `evolve_knowledge` and `merge_branch` probe calls are now unmetered, so `get_metrics` no longer reports double the actual number of tool invocations.

### Added
- `merge_branch` conflict responses now include a `field_level_auto_merge_note` when the ADR-007 fast path was unavailable, explaining why the conflict wasn't auto-resolved.

---

## [1.7.6] - 2026-07-26

### Changed
- Bumped `cks-runtime` dependency to `>=1.17.0` (adds field-level auto-merge for disjoint edits, ADR-007 Part 2). `merge_branch` and `merge_knowledge` automatically benefit from the new auto-resolution logic.

---

## [1.7.5] - 2026-07-26

### Changed
- Bumped `cks-runtime` dependency to `>=1.16.0` (adds operation log for field-level change tracking, ADR-007 Part 1).

---

## [1.7.4] - 2026-07-25

### Changed
- Updated `search_semantic` tool description to reflect that vector search is live and `seed_ids` is optional.
- `merge_knowledge` now reports `dropped_relations` in its response when referential integrity causes relations to be excluded.
- Bumped `cks-runtime` to `>=1.15.0` and `cks-core` to `>=1.11.0`.

### Fixed
- `merge_knowledge` no longer silently drops relations without informing the caller.

---

## [1.7.3] - 2026-07-25

### Added
- 7 new tests for `merge_knowledge` covering conflicts, resolutions (branch_a, branch_b, custom object, malformed, partial).
- 5 new tests for `merge_branch` with resolutions.
- Bumped `cks-runtime` dependency to `>=1.14.0`.

### Fixed
- `_parse_resolutions` now correctly handles raw JSON object definitions for custom resolutions in both merge tools.

---

## [1.7.2] - 2026-07-25

### Added
- `merge_branch` and `merge_knowledge` now accept raw JSON object definitions in the `resolutions` parameter, enabling custom synthesized conflict resolutions without pre-constructing KnowledgeObjects.
- 5 new tests covering all `resolutions` scenarios (branch_a, branch_b, custom object, partial, malformed).

### Changed
- Updated `merge_branch` conflict message to recommend using the `resolutions` parameter for a one-shot resolution.

---

## [1.7.1] - 2026-07-25

### Added
- `merge_branch` now accepts optional `resolutions` parameter, enabling partial merges with per-object conflict resolution strategies.
- Updated tool schema to document `resolutions` for `merge_branch`.

### Changed
- Improved default description for GPU in knowledge graph examples to enhance semantic search relevance.

---

## [1.7.0] - 2026-07-25

### Added
- `merge_knowledge` and `merge_branch` now accept an optional `resolutions` parameter for partial three-way merges, allowing callers to specify per-object conflict resolution strategies (`"branch_a"`, `"branch_b"`, `null`, or a custom object definition).
- Updated tool schema in `server.py` to document the `resolutions` parameter for both merge tools.
- Bumped `cks-runtime` dependency to `>=1.13.0` (adds `resolutions` support in `CoreBridge.merge()` and `MergeOperation`).

### Changed
- `search_semantic` now correctly triggers vector search when `seed_ids` is omitted or empty, instead of requiring explicit IDs. The parameter is no longer listed as required.

---

## [1.6.19] - 2026-07-24

### Fixed
- `validate_knowledge` now retrieves the correct (most recent) failed operation result when recovering diagnostics from a `RuntimeError`, ensuring detailed error messages are returned instead of a generic "Validation failed".
- Bumped `cks-runtime` to `>=1.11.0` (automatic `parent_version_id` for branches, improved diagnostics recording).

---

## [1.6.18] - 2026-07-24

### Fixed
- **Inconsistent error handling in `validate_knowledge`:** validation failures during commit (e.g., dangling references) now return structured diagnostics instead of a raw `RuntimeError` traceback.
- **`merge_knowledge` now returns structured diffs** for conflicts (`target_diff`/`source_diff`), matching `merge_branch`'s behavior instead of leaking Python `repr()` strings.
- **Updated `merge_branch` documentation** to reflect actual field names (`target_diff`/`source_diff` instead of `base_state`/`target_state`/`source_state`).

---

## [1.6.17] - 2026-07-24

### Changed
- Bumped `cks-runtime` dependency to `>=1.10.3` (fixes OutboxEmbeddingWorker crash, restoring semantic embedding generation and enabling `search_semantic` without explicit `seed_ids`).

---

## [1.6.16] - 2026-07-24

### Changed
- `search_semantic` now normalizes query vectors, improving semantic search accuracy when combined with normalized embeddings from `cks-runtime>=1.10.2`.
- Bumped `cks-runtime` dependency to `>=1.10.2`.

---

## [1.6.14] - 2026-07-24

### Changed
- Bumped `cks-runtime` to `>=1.10.0` — includes the new generalised Task Bus, enabling future background task types like conflict escalation.

---

## [1.6.13] - 2026-07-24

### Added
- `query_subgraph` now supports `compact_mode`. When set to `true`, the response contains arrays of `nodes` and `edges` instead of full canonical JSON, making the output significantly smaller and easier for LLMs to process.

---

## [1.6.12] - 2026-07-24

### Changed
- Merge conflict responses now include a human-readable `target_diff` and `source_diff` per conflict, instead of opaque `str()` dumps. This makes it easier for LLMs and users to understand what changed in each branch.
- Bumped `cks-runtime` to `>=1.9.5` (restores version history for persistent sessions).

---

## [1.6.11] - 2026-07-24

### Fixed
- **Provenance signing secret now persists across server restarts.** If `CKS_MCP_SECRET` is not set, the server generates a random secret on first launch and saves it to `data/.cks_provenance_secret`. Previously verified `VerificationRecord` objects remain valid after restart.

---

## [1.6.10] - 2026-07-24

### Fixed
- **`evolve_knowledge` now validates the evolved structure before committing.** If the evolution would produce an invalid structure (e.g., dangling references from a misused `remove_relation`), the commit is blocked with a clear error, preventing corrupted data from entering the session history.
- Bumped `cks-runtime` to `>=1.9.4` (fixes embedding worker for delta versions).

---

## [1.6.9] - 2026-07-24

### Fixed
- `search_semantic` now filters out `Relation` type objects from the vector search results, ensuring that only domain objects (Concepts, Documents, etc.) are returned as seeds.

---

## [1.6.8] - 2026-07-24

### Changed
- Bumped `cks-runtime` to `>=1.9.3` — embedding worker now excludes relation objects, so `search_semantic` no longer returns false positives like relation IDs.

---

## [1.6.7] - 2026-07-24

### Changed
- Bumped `cks-runtime` to `>=1.9.2` (updated HuggingFace API endpoint).

---

## [1.6.6] - 2026-07-24

### Fixed
- Global `socket.getaddrinfo` monkey-patch replaced with temporary thread-local override, restoring DNS resolution for non-verification HTTP requests (e.g., Hugging Face API).

---

## [1.6.5] - 2026-07-24

### Changed
- Switched to `HuggingFaceEmbeddingClient` for free, token-based semantic embeddings via Hugging Face Inference API. Requires `HF_TOKEN` environment variable.
- Bumped `cks-runtime` dependency to `>=1.9.1`.

---

## [1.6.4] - 2026-07-23

### Added
- Server now initializes `OpenAIEmbeddingClient` at startup, enabling real semantic embeddings for `search_semantic`. Falls back gracefully if `OPENAI_API_KEY` is not set or `openai` package is missing.

---

## [1.6.3] - 2026-07-23

### Changed
- `search_semantic` now uses the runtime's configured `EmbeddingClient` for query vectorization, enabling real semantic search when a real client is configured.
- Bumped `cks-runtime` dependency to `>=1.9.0`.

---

## [1.6.2] - 2026-07-23

### Fixed
- `search_semantic` now correctly triggers vector search when `seed_ids` is omitted or empty, instead of requiring explicit IDs. The parameter is no longer listed as required.

---

## [1.6.1] - 2026-07-23

### Changed
- Bumped `cks-runtime` dependency to `>=1.8.2` (fixes session association for embeddings; `search_semantic` now works without explicit seed_ids).

---

## [1.6.0] - 2026-07-23

### Changed
- `search_semantic` now uses vector embeddings for ANN search instead of requiring explicit `seed_ids`. Falls back gracefully if embeddings are unavailable.
- Bumped `cks-runtime` dependency to `>=1.8.1`.

---

## [1.5.4] - 2026-07-23

### Fixed
- **Content-Length parsing:** body is now read as bytes and decoded, fixing request corruption with multi-byte UTF-8 characters.
- **Off-by-one errors in `resources.py`:** `read_resource` now correctly resolves session, version-list, and specific-version URIs.

### Added
- `get_metrics` tool is now registered and exposed to clients.

---

## [1.5.3] - 2026-07-23

### Fixed
- Registered `get_metrics` tool in `server.py` — it was implemented but not exposed to clients, so LLMs couldn't discover it.

---

## [1.5.2] - 2026-07-23

### Added
- `get_metrics` tool — returns runtime metrics (invocation counts and average execution times per operation type).
- Bumped `cks-runtime` dependency to `>=1.6.2`.

---

## [1.5.1] - 2026-07-23

### Changed
- Bumped `cks-runtime` dependency to `>=1.6.1` (fixes a critical bug where `Dispatcher.dispatch()` was not instantiating operations correctly, causing crashes for any `DispatchRequest`-based transactions).

---

## [1.5.0] - 2026-07-23

### Added
- `search_semantic` tool — performs semantic search over a session's Knowledge Structure. Accepts a natural language query and seed IDs, then expands the neighbourhood using `query_subgraph`. This is the first step towards a full vector-index-powered RAG pipeline.

---

## [1.4.1] - 2026-07-23

### Added
- `evolve_knowledge` now returns an optional `cascade_removed_relations` field, listing relation IDs that were silently deleted because a referenced object was removed. This makes cascade side effects explicit and auditable.

---

## [1.4.0] - 2026-07-23

### Added
- **MCP Prompts:** the server now offers ready‑to‑use prompt templates (`create_knowledge_graph`, `verify_claim`, `explore_subgraph`, `branch_and_merge`) via `prompts/list` and `prompts/get`. Users can select a workflow from Claude Desktop's prompt menu and fill in parameters without knowing the tool names or JSON syntax.
- New module `prompts.py` implementing the prompt handlers.

---

## [1.3.5] - 2026-07-23

### Fixed
- **Session leak on provenance rejection:** `validate_knowledge` and `evolve_knowledge` (without `session_id`) no longer create and persist a session before checking provenance. A structure with a forged or missing `VerificationRecord` signature is fully rejected — no `session_id` is returned, and no session is registered in the runtime. Previously, the session was persisted immediately, making the forged content readable via `serialize_knowledge`, `explain_knowledge`, `query_subgraph`, and MCP Resources.
- **Severity-blind blocking:** `evolve_knowledge`, `merge_knowledge`, and `merge_branch` now block only on `error`-severity provenance diagnostics (forged/ambiguous signatures). `warning`-severity diagnostics (e.g. a genuinely-signed but as-yet-unlinked `VerificationRecord`) no longer prevent a legitimate commit, restoring the two-step workflow of adding a signed record and linking it in separate operations.
- **Truthiness bug in `merge_branch`:** `if probe.payload` replaced with `if probe.payload is not None` to avoid skipping provenance check on empty but valid merged structures.
- Updated regression tests to cover session leak, severity-aware blocking, and false-positive unlinked-record scenario (50/50 tests passing).

---

## [1.3.4] - 2026-07-23

### Changed
- Bumped `cks-runtime` dependency to `>=1.6.0`. Sessions and versions now persist across server restarts, fully restoring the operational state when Claude Desktop reconnects or the server process is restarted.

### Fixed
- After a server restart, all previously created sessions are now immediately available via `get_session()`, `list_sessions`, and the MCP Resources surface. No data is lost.

---

## [1.3.3] - 2026-07-22

### Fixed
- **Remaining provenance bypass in `validate_knowledge`:** the provenance-signature gate added in 1.2.6 covered `evolve_knowledge` and `merge_knowledge`/`merge_branch`, but not `validate_knowledge` itself -- which is the tool that actually creates a session's first committed version. It previously committed unconditionally and only checked `VerificationRecord` signatures afterward to set the response's `valid` field, so a forged record still ended up as a real, persisted version regardless of `valid: false` -- visible to `serialize_knowledge`, `explain_knowledge`, `query_subgraph`, and the MCP Resources surface with no indication it had failed a check. `validate_knowledge` now verifies provenance before deciding whether to commit at all, mirroring the existing dry-run-then-commit pattern; a structure with a forged or missing signature is validated (all core-level diagnostics still returned) but never committed, and the response omits `version_id` entirely rather than returning one for a version that doesn't exist.
- 5 new regression tests covering the forged-signature, missing-signature, genuine-signature, re-validation-of-an-existing-session, and no-VerificationRecord-present cases.

---

## [1.3.2] - 2026-07-22

### Added
- **Demo GIF** showing a complete CKS workflow from a single sentence ("Use cks-mcp to create a knowledge graph about the water cycle…"), including validation and explanation, all within Claude Desktop.
- Simplified **Quick Start** section explaining that CKS is just a conversation — no programming, no command line.

### Changed
- Updated README with demo GIF, streamlined installation instructions, and a new `query_subgraph` usage example.

---

## [1.3.1] - 2026-07-22

### Fixed
- Added `"resources": {}` to the server's `initialize` capabilities, enabling clients to discover MCP Resources.

---

## [1.3.0] - 2026-07-22

### Added
- **MCP Resources:** the server now exposes active sessions, their version histories, and each version's Knowledge Structure as virtual resources (`cks://sessions/...`). LLMs can read them directly without calling tools, making the knowledge graph instantly browsable.
- New module `resources.py` implementing `resources/list` and `resources/read` handlers.

---

## [1.2.6] - 2026-07-22

### Fixed
- **Critical provenance bypass:** `evolve_knowledge` and `merge_branch`/`merge_knowledge` now verify `VerificationRecord` signatures before committing new state. Previously, a hand‑written record with a fake signature could be inserted via evolution or merging, circumventing the check that `validate_knowledge` applies. This restores the invariant that only genuinely verified sources can appear as `VerificationRecord` objects in any session history.
- Extracted `verify_structure_provenance` into `provenance.py` as a shared helper, used by all tools that modify knowledge state.

---

## [1.2.5] - 2026-07-22

### Fixed
- Server now automatically falls back to a writable temporary directory (or in‑memory storage) when the default `data/` directory is read‑only, such as in Claude Desktop's sandboxed environment. This prevents `OSError: [Errno 30] Read-only file system` crashes.

---

## [1.2.4] - 2026-07-22

### Fixed
- Server now explicitly creates the `data/` directory for SQLite storage on startup, preventing crashes when Claude Desktop launches the server in a clean environment.
- Improved error logging during server initialization.

---

## [1.2.3] - 2026-07-22

### Changed
- Enabled persistent SQLite storage by default (`cks_mcp.db`), using `cks-runtime>=1.5.1`. Sessions and versions now survive server restarts.
- Bumped `cks-runtime` dependency to `>=1.5.1`.

---

## [1.2.2] - 2026-07-22

### Added
- Structured JSON logging for every tool invocation (written to stderr), recording tool name, session_id, duration_ms, and success/error.
- Subscription to Runtime lifecycle events (`SessionCreated`, `TransactionCommitted`, `VersionCreated`, `ValidationFailed`, etc.) — all events are logged as JSON lines, providing a full operational audit trail.

---

## [1.2.1] - 2026-07-22

### Changed
- Bumped `cks-runtime` dependency to `>=1.4.1` and `cks-core` to `>=1.9.1` (includes query_subgraph ordering and relation-as-seed fixes).

---

## [1.2.0] - 2026-07-22

### Added
- `query_subgraph` tool – extracts a k‑hop neighbourhood from a session's Knowledge Structure as a self‑contained subgraph, with optional relation/object type filters and a token/object budget that ranks candidates by degree, type weight, and distance. Returns full truncation metadata (`total_found_nodes`, `returned_nodes`, `is_truncated`, `truncation_reason`, `suggested_next_seed`) so an LLM agent always knows whether the neighbourhood was truncated and can resume from the suggested next seed.
- Bumped `cks-runtime` dependency to `>=1.4.0` and `cks-core` to `>=1.9.0`.

---

## [1.1.1] - 2026-07-22

### Fixed
- `explain_knowledge` with `session_id` no longer creates a new empty version in the session's history. Read-only explanations now bypass the transaction pipeline and use the executor directly, preventing version history pollution. (#bug 1)
- Bumped `cks-runtime` dependency to `>=1.3.2` and `cks-core` to `>=1.8.3`.

---

## [1.1.0] - 2026-07-21

### Added
- `create_branch` tool — fork a new session from an existing one, optionally from a specific historical version, for isolated experimentation without touching the parent session.
- `merge_branch` tool — session-aware three-way merge between a target session and a branch session. Unlike `merge_knowledge`, the merge base is resolved automatically from the branch's recorded fork point; on success the merged result is committed as a new version of the target session, on conflict a structured `conflicts` list (`object_id`, `base_state`, `target_state`, `source_state`) is returned instead, with guidance not to retry `merge_branch` unchanged but to resolve conflicts via `evolve_knowledge`.
- `close_session` tool — closes a session, intended for releasing a branch session once `merge_branch` has integrated it.
- Bumped `cks-runtime` dependency to `>=1.3.0` for `Runtime.create_branch`, `CoreBridge.merge`/`supports_merge`, and `MergeOperation`.

---

## [1.0.10] - 2026-07-21

### Fixed
- `merge_knowledge` now correctly returns detailed conflict information (object_id, base, branch_a, branch_b) when a `MergeConflictError` occurs, using duck-typing instead of fragile class name checks.

---

## [1.0.9] - 2026-07-21

### Fixed
- `merge_knowledge` tool now correctly handles `MergeConflictError` without relying on direct imports.

---

## [1.0.8] - 2026-07-21

### Changed
- Bumped `cks-runtime` to `>=1.2.3` and `cks-core` to `>=1.8.2` for merge support.
- `merge_knowledge` tool – three-way merge of Knowledge Structures with conflict detection.

---

## [1.0.7] - 2026-07-21

### Changed
- Bumped `cks-runtime` dependency to `>=1.2.2` for full compatibility with delta version storage and performance improvements from `cks-core` v1.8.0.

---

## [1.0.6] - 2026-07-21

### Changed
- `compare_versions` now uses `session.get_version_state()` to reconstruct base versions, compatible with `cks-runtime` v1.2.0's delta version storage.

---

## [1.0.5] - 2026-07-20

### Fixed
- Server no longer crashes with an unhandled `ValueError` when a client sends a malformed `Content-Length` header. The error is now caught and returned as a proper JSON-RPC parse error, keeping the server alive for subsequent requests.

---

## [1.0.4] - 2026-07-20

### Fixed
- `compare_versions` no longer crashes with "Object of type RemoveRelation is not JSON serializable" when the diff contains relation removals. The serialiser now correctly handles all four operator types.

---

## [1.0.3] - 2026-07-20

### Fixed
- `compare_versions` now correctly computes the diff from `base_version` to `current`, and returns explicit `direction`, `base_version_id`, `current_version_id`, and a semantic `summary` (counts of added/removed objects and relations). This makes the diff direction unambiguous for LLMs.
- `ValidateOperation` now correctly returns `FAILED` status when the structure is invalid, preventing invalid structures from being committed as versions.
- `TransactionManager._finish` now removes completed transactions from the registry, preventing memory leaks.
- `Dispatcher.dispatch` no longer writes to the non-existent `context.diagnostics`.
- `CoreBridge.validate` now passes `extra_constraints` even when empty (`is not None` check).

### Added
- Integration tests for `compare_versions` direction and `TransactionManager` cleanup (2 new tests, total 30 passed).

---

## [1.0.2] - 2026-07-20

### Changed
- `compare_versions` now returns explicit `direction`, `base_version_id`, `current_version_id`, and a semantic `summary` (counts of added/removed objects and relations), making the diff direction unambiguous for LLMs.
- Updated tool description in `server.py` to document the new response format.

---

## [1.0.1] - 2026-07-20

### Added
- `compare_versions` tool: computes the structural diff between the current state of a session and a specified target version, returning a compact list of changes.
- Session-aware `serialize_knowledge`, `explain_knowledge`, and `evolve_knowledge` — all tools now accept an optional `session_id` to operate on existing sessions.
- Stable provenance secret via `CKS_MCP_SECRET` env var.

### Changed
- `verify_source` now uses deterministic, IPv4-first IP selection with automatic fallback.
- `VerificationRecord` shape and provenance checks are now unconditional, regardless of the `verification_record` extension parameter.
- Improved error responses for LLM readability.

---

## [1.0.0] - 2026-07-19

### Added
- First stable release of the CKS MCP Server.
- Unconditional verification of `VerificationRecord` shape and provenance, regardless of whether the `verification_record` extension is explicitly requested.
- Deterministic, IPv4-first IP candidate selection in `verify_source` with automatic fallback to additional resolved addresses.
- Updated tests covering the new IP resolution contract and fallback behaviour (32 tests total).

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
