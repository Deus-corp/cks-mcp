# Request Lifecycle

How a request actually flows through the components in
[Architecture](ARCHITECTURE.md), using `validate_knowledge` — the most
involved tool — as the walkthrough. Simpler tools follow the same shape
with fewer steps.

## `validate_knowledge` with a fresh `json_data` payload

1. **Transport.** `server.py` reads a JSON-RPC `tools/call` request from
   stdin and dispatches it to the wrapped `validate_knowledge` handler.
2. **Middleware.** The composed stack runs first: `require_fields` checks
   that a required argument isn't missing; if `session_id` were given
   instead, `require_session`/`require_open_session` would resolve and
   check it before the handler ever runs.
3. **Parsing.** The handler parses `json_data` into a `KnowledgeStructure`
   via `cks-core`. A `cks.SerializationError` here short-circuits into a
   structured `invalid_json` error — nothing downstream runs.
4. **Extension resolution.** Any requested `extensions` names are resolved
   to `cks-core` `Constraint` objects. An unrecognized name short-circuits
   into an `unknown_extension` error. If the structure contains a
   `VerificationRecord`, the `verification_record` extension is force-added
   regardless of what was requested — see
   [Extension Model](../extensions.md#why-unconditional-enforcement-matters).
5. **Provenance check — before any session is registered.** The structure
   is checked for `VerificationRecord` objects and their HMAC signatures,
   using a throwaway, unregistered `RuntimeSession` rather than
   `runtime.create_session()`. This ordering matters: `create_session`
   persists immediately, and if it ran before this check, a forged record
   would already be live and readable via `serialize_knowledge`,
   `query_subgraph`, or an MCP Resource on the returned `session_id` — even
   though the response correctly reported it as invalid. See
   [Security Model](../security.md#provenance-enforcement).
6. **Branch on provenance result:**
   - **Provenance OK:** *now* `runtime.create_session()` registers the
     session for real, a `Transaction` is opened, a `ValidateOperation`
     is added and committed. `cks-core`'s own validation pipeline runs
     inside that commit, producing the first layer of diagnostics.
   - **Provenance failed:** the operation runs once, straight through the
     executor, bypassing the transaction/commit pipeline entirely — core
     diagnostics are still collected for a complete report, but no
     session is registered and no version is created.
7. **Response assembly.** Core diagnostics and provenance diagnostics are
   combined; `valid` is `true` only if both passed. `session_id` is
   included only if a session actually exists (registered in step 6);
   `version_id` only if a version actually committed.
8. **Transport.** `server.py` serializes the response dict back over
   stdout as the JSON-RPC result.

## What's common to every tool

- **Middleware runs before the handler body**, so field/session checks
  never depend on the handler remembering to do them itself.
- **`catch_unhandled_errors` is the outermost layer** — any exception that
  escapes a handler becomes a structured `internal_error` response, never
  a raw traceback reaching the LLM client (except `asyncio.CancelledError`,
  which must propagate for cooperative cancellation).
- **Mutating tools dry-run before they commit.** `evolve_knowledge`,
  `merge_branch`, `merge_knowledge`, and `fork_sandbox` all validate the
  *prospective* result — including provenance — before opening a
  transaction, for the same reason step 5 above runs before
  `create_session`: a persisted version is trusted by every downstream
  reader, so nothing partially-invalid is ever allowed to become one.
- **Every committed change is observed twice.** `observability.py`
  subscribes to `cks-runtime`'s EventBus and logs structured events
  (`SessionCreated`, `TransactionCommitted`, ...) to stderr; `telemetry.py`
  independently aggregates per-tool call counts and latencies for
  `get_metrics`, from the same call.

See [Architecture](ARCHITECTURE.md) for what each component in this flow
is responsible for, and [Tools Reference](../tools/index.md) for the
request/response shape of every individual tool.
