"""
Optional gossip integration for cks-mcp (Вариант 1).

Wires cks_runtime's ``GossipAdapter`` / ``GossipServer`` / ``GossipService``
into the MCP server process, so several running instances of cks-mcp
(e.g. several Claude Desktop processes on different machines, or on the
same machine talking over localhost) can automatically anti-entropy
their knowledge-structure Sessions with each other -- a change one user
makes shows up for another without a manual export/import round trip.

Off by default: enabling it means this process starts listening on a
TCP port and dialing out to configured peers, which is a meaningfully
different trust/network posture than a plain stdio MCP server. Opt in
explicitly with ``CKS_GOSSIP_ENABLED=true``.

Configuration is env-var-based (``CKS_GOSSIP_*``), matching how
``server.py`` already resolves ``CKS_EMBEDDING_PROVIDER`` and friends --
these are per-deployment operational settings, not Runtime-owned state,
so they deliberately do not live on ``cks_runtime.config.RuntimeConfig``
(whose own docstring scopes it to Runtime-wide behaviour, not transport
concerns; ``GossipService``/``GossipServer`` already take host/port/
peers/secret as plain constructor arguments, not through a config
object, in cks-runtime's own ``examples/local_cluster_demo.py``).

The HMAC signing secret is handled entirely by
``cks_runtime.gossip.secret.load_secret`` (``CKS_GOSSIP_SECRET`` env var,
else a persisted per-installation file, else generated on first use) --
no separate cks-mcp setting for it, so every replica sharing one
``~/.cks_runtime`` directory (or one ``CKS_GOSSIP_SECRET``) already
agrees on it.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from cks_runtime.events.runtime_event import (
    GossipConflictDetected,
    SessionClosed,
    SessionCreated,
)
from cks_runtime.gossip.adapter import GossipAdapter
from cks_runtime.gossip.discovery import PeerDiscovery
from cks_runtime.gossip.http_transport import (
    GossipServer,
    HTTPGossipTransport,
    HTTPPeerDiscovery,
)
from cks_runtime.gossip.scheduling import PeerScheduler
from cks_runtime.gossip.secret import load_secret
from cks_runtime.gossip.service import GossipService
from cks_runtime.runtime import Runtime

from cks_mcp.conflict_inbox import conflict_inbox

__all__ = ["GossipHandle", "GossipSettings", "setup_gossip"]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True, slots=True)
class GossipSettings:
    """
    Resolved ``CKS_GOSSIP_*`` environment configuration.

    ``host`` defaults to ``127.0.0.1``, deliberately *not*
    ``GossipServer``'s own ``0.0.0.0`` default -- an MCP server that has
    never listened on a network port before should not start doing so
    beyond localhost without the operator asking for it explicitly via
    ``CKS_GOSSIP_HOST``.
    """

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    peers: tuple[str, ...] = ()
    interval_s: float = 5.0
    self_address: str | None = None
    discovery: bool = False

    @classmethod
    def from_env(cls) -> GossipSettings:
        peers_raw = os.environ.get("CKS_GOSSIP_PEERS", "")
        peers = tuple(p.strip() for p in peers_raw.split(",") if p.strip())

        port_raw = os.environ.get("CKS_GOSSIP_PORT", "8765")
        interval_raw = os.environ.get("CKS_GOSSIP_INTERVAL_S", "5.0")

        return cls(
            enabled=_env_bool("CKS_GOSSIP_ENABLED", False),
            host=os.environ.get("CKS_GOSSIP_HOST", "127.0.0.1"),
            port=int(port_raw),
            peers=peers,
            interval_s=float(interval_raw),
            self_address=os.environ.get("CKS_GOSSIP_SELF_ADDRESS") or None,
            discovery=_env_bool("CKS_GOSSIP_DISCOVERY", False),
        )


@dataclass
class GossipHandle:
    """Owns the running gossip components; started/stopped as a unit."""

    adapter: GossipAdapter
    server: GossipServer
    service: GossipService

    async def start(self) -> None:
        # Server first: a peer's inbound round arriving between
        # service.start() and server bind-up would otherwise fail for
        # no good reason.
        await self.server.start()
        await self.service.start()

    async def stop(self) -> None:
        await self.service.stop()
        await self.server.stop()


def setup_gossip(runtime: Runtime, settings: GossipSettings) -> GossipHandle | None:
    """
    Build (but do not start -- see ``GossipHandle.start``) the gossip
    components for ``runtime``, if ``settings.enabled``.

    Returns ``None`` (gossip left off) when:
    - ``settings.enabled`` is false (the default);
    - ``runtime.replica_id`` is ``None`` -- this Runtime's storage
      backend has no durable per-process identity to gossip under
      (``InMemoryStorage`` restarts fresh every time, for instance).

    Subscribes to ``SessionCreated``/``SessionClosed`` so the tracked
    session set stays in sync with this process's own Sessions from
    here on, and seeds it with every Session already restored from
    storage at startup (those predate this call and never fired
    ``SessionCreated``). Also subscribes to ``GossipConflictDetected``,
    buffering it into ``conflict_inbox`` for an external Critic agent
    to drain via the ``list_gossip_conflicts`` tool -- the event only
    ever fires once gossip is running, so this subscription is scoped
    to here rather than ``observability.py``'s always-on lifecycle
    logging.
    """
    if not settings.enabled:
        return None

    if runtime.replica_id is None:
        print(
            "[CKS-MCP] WARNING: CKS_GOSSIP_ENABLED=true but this storage "
            "backend has no replica_id (no durable gossip identity). "
            "Skipping gossip startup.",
            file=sys.stderr,
        )
        return None

    secret = load_secret()
    adapter = GossipAdapter(runtime, runtime.replica_id)
    scheduler = PeerScheduler(list(settings.peers))

    server = GossipServer(
        adapter,
        secret=secret,
        host=settings.host,
        port=settings.port,
        known_peers=(lambda: scheduler.peers) if settings.discovery else None,
        self_address=settings.self_address,
    )

    discovery: PeerDiscovery | None = HTTPPeerDiscovery() if settings.discovery else None

    service = GossipService(
        adapter,
        transport=HTTPGossipTransport(),
        scheduler=scheduler,
        secret=secret,
        interval_s=settings.interval_s,
        discovery=discovery,
        self_address=settings.self_address,
        # Shared explicitly so server replies and this service's own
        # outgoing rounds never hand out overlapping seq_no values
        # without relying on the same-file fallback (seq_no.py).
        seq_no_counter=server.seq_no_counter,
    )

    for session in runtime.list_sessions():
        service.track_session(session.session_id)

    def _on_created(event: SessionCreated) -> None:
        service.track_session(event.session_id)

    def _on_closed(event: SessionClosed) -> None:
        service.untrack_session(event.session_id)

    async def _on_conflict(event: GossipConflictDetected) -> None:
        await conflict_inbox.record(event)

    runtime.events.subscribe(SessionCreated, _on_created)
    runtime.events.subscribe(SessionClosed, _on_closed)
    runtime.events.subscribe(GossipConflictDetected, _on_conflict)

    print(
        f"[CKS-MCP] Gossip enabled: listening on {settings.host}:{settings.port}, "
        f"peers={list(settings.peers)}, discovery={settings.discovery}, "
        f"replica_id={runtime.replica_id}",
        file=sys.stderr,
    )

    return GossipHandle(adapter=adapter, server=server, service=service)
