# ADR-003

# Composable Middleware Stack

**Status:** Accepted

**Date:** 2026-07-30 (introduced in `v1.16.0`)

**Category:** Architecture Decision Record

> **Note (v1.17.0):** `tool_registry.py`, referenced throughout this ADR,
> was renamed to `registry.py` during the project restructuring. The
> decision and reasoning below are unchanged — only the filename moved.

---

# Context

Before `v1.16.0`, each tool handler in `tools/` was responsible for its own
argument validation: checking required fields were present, resolving a
`session_id` to an actual session, and checking that session wasn't
closed. This logic was small per handler, but repeated across all 24 of
them, wrapped ad hoc around calls to `log_tool_call()`.

# Problem

Twenty-four handlers each hand-rolling the same three or four checks meant:

- inconsistent error responses between tools for the same class of
  mistake (a missing field, an unknown session) depending on how carefully
  each handler had been written;
- no single place to add a new cross-cutting concern (e.g. per-tool
  latency tracking for `get_metrics`) without touching all 24 files;
- unhandled exceptions in a handler could, in principle, surface as a raw
  traceback to the LLM client instead of a structured error, depending on
  whether that particular handler happened to catch it.

# Decision

Introduce `middleware.py`: a small set of composable decorator factories
(`require_fields`, `require_session`, `require_open_session`,
`catch_unhandled_errors`) plus a `with_middleware` composition helper, and
route every tool through `_wrap` / `_wrap_session` / `_wrap_open_session`
builders in `tool_registry.py` instead of ad hoc per-handler checks.

```python
handler = with_middleware(
    catch_unhandled_errors,
    log_tool_call("my_tool"),
    require_session("session_id"),
    require_open_session("session_id"),
)(my_tool_fn)
```

The first item in `with_middleware`'s argument list is the *outermost*
layer — it runs first on the way in and last on the way out — matching
the natural top-to-bottom reading order of the stack.

At the same time, `log_tool_call` was extended to feed a new
`ToolTelemetry` singleton (`telemetry.py`), so every tool gets call-count,
success-rate, and latency-percentile tracking automatically, surfaced via
`get_metrics`'s `tool_telemetry` field, without each handler doing
anything extra.

# Consequences

Positive:

- Every tool gets the same structured error for the same class of mistake
  — `missing_parameter`, `session_not_found`, `session_closed` — by
  construction, not by convention.
- `catch_unhandled_errors` as the guaranteed outermost layer means no
  handler can leak a raw exception to the client, regardless of whether
  its author thought to add a try/except.
- Adding a new cross-cutting concern (telemetry was the first; more could
  follow) means changing `middleware.py` and `tool_registry.py`'s wiring,
  not 24 individual files.
- New tools inherit the full stack by using the same `_wrap*` builders,
  rather than a contributor needing to remember which checks to hand-copy
  from an existing handler.

Negative:

- An extra layer of indirection between `tool_registry.py`'s dispatch and
  the actual handler body — reading what a tool does now means reading
  both the handler and its middleware stack in `tool_registry.py`.
- Middleware ordering matters (`require_open_session` should sit inside
  `require_session` so existence is checked first) — a subtle contract
  that isn't enforced by the type system, only by convention and the
  docstring in `middleware.py`.

# Alternatives Considered

## Shared validation helper functions, called manually

Extract the repeated checks into plain functions each handler calls at
its top. Rejected: this still requires every handler (and every new one)
to remember to call them, and in the right order — it fixes duplication
but not the "did this handler remember" problem middleware solves by
construction.

## A single monolithic `@validate_tool_call` decorator

One decorator handling all cases via configuration flags. Rejected: the
composability of small, single-purpose middleware (`require_fields` alone
for a read tool with no session; the full stack for a mutating tool) is
more flexible than one decorator trying to cover every combination via
parameters, and keeps each concern independently testable.

# Rationale

Cross-cutting concerns that apply to most or all of 24 handlers are much
easier to keep consistent, and to extend later, as a shared, composable
layer than as convention every handler author has to remember and apply
correctly by hand.

# Status

Accepted, and already in production use — every tool in `tool_registry.py`
is wired through this stack.
