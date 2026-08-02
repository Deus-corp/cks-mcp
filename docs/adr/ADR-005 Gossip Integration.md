# ADR-005

# Gossip Integration (Multi-Instance Session Sync)

**Status:** Accepted

**Date:** 2026-08-02

**Category:** Architecture Decision Record

---

# Context

`cks-runtime` (ADR-008, `cks_runtime.gossip`) already ships a working
anti-entropy gossip stack — `GossipAdapter` (merge semantics),
`GossipServer`/`HTTPGossipTransport` (the wire protocol), `PeerScheduler`
(peer choice + backoff), and `GossipService` (the periodic round). Until
now the only place that wired all of these together was
`cks-runtime/examples/local_cluster_demo.py` — a standalone script, not
something a `cks-mcp` deployment could turn on.

Each `cks-mcp` process (e.g. one per Claude Desktop installation) owns
its own `Runtime` and its own storage. Two people — or one person on two
machines — each running their own `cks-mcp` had no way to converge on a
shared Session without exporting and re-importing it by hand.

# Problem

Making gossip available to real `cks-mcp` deployments needs answers to
three things the demo script didn't have to address, because it ran
every "peer" as a trusted, hand-configured process in one Python
program:

1. **Which Sessions get gossiped, and when do they start/stop being
   tracked?** The demo calls `service.track_session(session_id)` by
   hand, once, for a session it already knows about. A running
   `cks-mcp` server creates and closes Sessions continuously, driven by
   tool calls it doesn't control the timing of.
2. **Where do peer addresses and the network posture (host/port) come
   from?** `cks-mcp` has never opened a listening socket before —
   enabling gossip is a real change in what the process does on the
   network, not just an internal config toggle.
3. **Where does this configuration live?** `cks_runtime.config.RuntimeConfig`
   is explicitly scoped ("Runtime-wide options... configuration never
   owns Runtime state") and is shared by every consumer of
   `cks-runtime`, not just `cks-mcp`.

# Decision

Add `cks_mcp/gossip.py`:

- `GossipSettings.from_env()` resolves `CKS_GOSSIP_*` environment
  variables (`ENABLED`, `HOST`, `PORT`, `PEERS`, `INTERVAL_S`,
  `SELF_ADDRESS`, `DISCOVERY`), following the exact pattern
  `server.py` already uses for `CKS_EMBEDDING_PROVIDER` and friends —
  per-deployment operational settings as environment variables read at
  server startup, not as fields on the shared `RuntimeConfig` dataclass.
  `GossipService`/`GossipServer` already take these as plain constructor
  arguments in cks-runtime's own demo, so nothing about wiring them
  through `RuntimeConfig` was actually required by the lower layer.
- `setup_gossip(runtime, settings)` builds (but does not start) a
  `GossipHandle` wrapping the adapter/server/service triple, returning
  `None` when gossip is disabled (the default) or when
  `runtime.replica_id` is `None` (a storage backend with no durable
  identity to gossip under). It seeds the tracked-session set from
  `runtime.list_sessions()` (Sessions restored from storage before
  gossip started) and subscribes to `SessionCreated`/`SessionClosed` on
  the Runtime's `EventBus` to keep it in sync from then on.
- `server.py` calls `setup_gossip` once, right after
  `setup_event_subscriptions`, and starts/stops the resulting handle
  around the stdio request loop (`try`/`finally`, alongside
  `runtime.aclose()`).
- **Off, and bound to `127.0.0.1`, by default.** `GossipServer`'s own
  default host is `0.0.0.0`; `cks-mcp` overrides that default to
  `127.0.0.1` in `GossipSettings`, so opting in without setting
  `CKS_GOSSIP_HOST` explicitly does not expose the process beyond
  localhost.
- The HMAC signing secret is *not* a new `cks-mcp` setting — it's
  `cks_runtime.gossip.secret.load_secret()` unchanged (`CKS_GOSSIP_SECRET`
  env var, else a persisted file, else generated on first use), so every
  replica sharing a secret already has one consistent way to do it.

As a prerequisite, this also fixes a latent bug found while building
the tracking-via-events piece: `Runtime.create_session` / `create_branch`
/ `close_session` never actually published `SessionCreated` /
`SessionClosed` on the `EventBus`, despite `cks-mcp`'s own
`observability.py` (and its CHANGELOG) already documenting a
subscription to them. See `cks-runtime`'s CHANGELOG entry — this repo's
gossip auto-tracking depends on that fix.

# Consequences

Positive:

- Several `cks-mcp` instances can converge on a shared Session
  automatically, with a single environment variable turning it on, no
  code change and no manual `track_session` bookkeeping.
- Safe-by-default network posture: opt-in, localhost-only unless told
  otherwise.
- Fixed the `SessionCreated`/`SessionClosed` gap also benefits the
  pre-existing structured lifecycle logging in `observability.py`,
  which silently never fired for those two event types before now.

Negative:

- Peer discovery is still address-list-based unless `CKS_GOSSIP_DISCOVERY`
  is turned on (peer-exchange piggy-backed on successful rounds,
  `cks_runtime.gossip.discovery`) — there is no zero-configuration LAN
  discovery (mDNS or similar).
- Every peer must agree on the same gossip secret out of band (shared
  `CKS_GOSSIP_SECRET`, or the same `~/.cks_runtime` directory) — this
  ADR does not add a secret-distribution mechanism.
- A `cks-mcp` process that never previously opened a network port now
  can; operators enabling `CKS_GOSSIP_HOST=0.0.0.0` (or any
  non-localhost value) should treat that the same as any other service
  they expose on their network.

# Alternatives Considered

## Gossip settings on `RuntimeConfig`

Rejected for the reason in *Decision* above: `RuntimeConfig` is shared,
Runtime-scoped, and every other piece of `cks-mcp`'s own operational
configuration (embedding provider, LLM provider, data directory) already
lives as `cks-mcp`-level environment variables instead, for the same
reason — these are choices about how *this deployment* of `cks-mcp` runs,
not state the `Runtime` object itself owns.

## Track every Session unconditionally, no opt-out

Considered gossiping all Sessions with no way to exclude one. Left for a
later iteration (`untrack_session` is already exposed on `GossipService`
and reachable from `GossipHandle.service` for a future tool or setting to
call) — not needed for the first version, since `SessionClosed` already
stops gossiping a Session the moment it's closed.

# Rationale

The gossip mechanism itself was already correct and tested in
`cks-runtime`; what was missing was purely the wiring — deciding *when*
Sessions are tracked, *what* the default network posture is, and *where*
the small amount of new configuration belongs — matching decisions
`cks-mcp` had already made once for embeddings and LLM provider
selection.

# Status

Accepted. `cks_mcp/gossip.py`, off by default, wired into `server.py`'s
`main()`.
