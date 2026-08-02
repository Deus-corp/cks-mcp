"""
Unit tests for cks_mcp.gossip (Вариант 1: gossip integration in cks-mcp).

Covers:
- GossipSettings.from_env: defaults, full parsing, CKS_GOSSIP_PEERS
  splitting/whitespace handling.
- setup_gossip: off by default, skipped when the Runtime has no
  replica_id, and (when enabled) seeds tracked sessions from
  Runtime.list_sessions() and stays in sync via SessionCreated /
  SessionClosed.
- GossipHandle.start()/stop() actually bind/release a real local port.
"""

from __future__ import annotations

import socket

import cks
import pytest
from cks_runtime.events.runtime_event import SessionClosed, SessionCreated
from cks_runtime.runtime import Runtime
from cks_runtime.storage.memory_storage import InMemoryStorage
from cks_runtime_plugins.cks_core import CksCoreAdapter

from cks_mcp.gossip import GossipSettings, setup_gossip

pytestmark = pytest.mark.asyncio


def _free_port() -> int:
    """Ask the OS for a currently-unused localhost TCP port (mirrors
    cks-runtime's tests/unit/gossip/test_http_transport.py helper)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _structure(obj_id: str) -> cks.KnowledgeStructure:
    return cks.KnowledgeStructure(
        [cks.KnowledgeObject(cks.ObjectIdentity(id=obj_id, type="Thing", name=obj_id))]
    )


# ---------------------------------------------------------------------------
# GossipSettings.from_env
# ---------------------------------------------------------------------------


def test_defaults_are_disabled_and_localhost(monkeypatch):
    for name in (
        "CKS_GOSSIP_ENABLED",
        "CKS_GOSSIP_HOST",
        "CKS_GOSSIP_PORT",
        "CKS_GOSSIP_PEERS",
        "CKS_GOSSIP_INTERVAL_S",
        "CKS_GOSSIP_SELF_ADDRESS",
        "CKS_GOSSIP_DISCOVERY",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = GossipSettings.from_env()

    assert settings.enabled is False
    assert settings.host == "127.0.0.1"
    assert settings.port == 8765
    assert settings.peers == ()
    assert settings.interval_s == 5.0
    assert settings.self_address is None
    assert settings.discovery is False


def test_from_env_parses_all_fields(monkeypatch):
    monkeypatch.setenv("CKS_GOSSIP_ENABLED", "true")
    monkeypatch.setenv("CKS_GOSSIP_HOST", "0.0.0.0")
    monkeypatch.setenv("CKS_GOSSIP_PORT", "9001")
    monkeypatch.setenv(
        "CKS_GOSSIP_PEERS", " http://127.0.0.1:9002 , http://127.0.0.1:9003,,"
    )
    monkeypatch.setenv("CKS_GOSSIP_INTERVAL_S", "1.5")
    monkeypatch.setenv("CKS_GOSSIP_SELF_ADDRESS", "http://127.0.0.1:9001")
    monkeypatch.setenv("CKS_GOSSIP_DISCOVERY", "yes")

    settings = GossipSettings.from_env()

    assert settings.enabled is True
    assert settings.host == "0.0.0.0"
    assert settings.port == 9001
    # Blank entries from stray commas are dropped, whitespace trimmed.
    assert settings.peers == ("http://127.0.0.1:9002", "http://127.0.0.1:9003")
    assert settings.interval_s == 1.5
    assert settings.self_address == "http://127.0.0.1:9001"
    assert settings.discovery is True


def test_enabled_accepts_common_truthy_spellings(monkeypatch):
    for value in ("1", "true", "True", "yes", "on"):
        monkeypatch.setenv("CKS_GOSSIP_ENABLED", value)
        assert GossipSettings.from_env().enabled is True

    for value in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("CKS_GOSSIP_ENABLED", value)
        assert GossipSettings.from_env().enabled is False


def test_empty_peers_string_yields_empty_tuple(monkeypatch):
    monkeypatch.setenv("CKS_GOSSIP_PEERS", "")
    assert GossipSettings.from_env().peers == ()


# ---------------------------------------------------------------------------
# setup_gossip
# ---------------------------------------------------------------------------


async def test_disabled_by_default_returns_none():
    runtime = await Runtime.create(core=CksCoreAdapter(), storage=InMemoryStorage())
    try:
        handle = setup_gossip(runtime, GossipSettings())
        assert handle is None
    finally:
        await runtime.aclose()


async def test_skips_when_runtime_has_no_replica_id():
    """A bare Runtime(...) (never ran .create()) has replica_id=None --
    setup_gossip must not try to build gossip components against it."""
    runtime = Runtime(core=CksCoreAdapter())
    assert runtime.replica_id is None

    settings = GossipSettings(enabled=True, port=_free_port())
    handle = setup_gossip(runtime, settings)

    assert handle is None


async def test_enabled_seeds_tracked_sessions_from_existing_sessions():
    runtime = await Runtime.create(core=CksCoreAdapter(), storage=InMemoryStorage())
    try:
        session = await runtime.create_session(_structure("pre-existing"))

        settings = GossipSettings(enabled=True, port=_free_port())
        handle = setup_gossip(runtime, settings)

        assert handle is not None
        assert session.session_id in handle.service.tracked_sessions
    finally:
        await runtime.aclose()


async def test_session_created_and_closed_keep_tracked_set_in_sync():
    runtime = await Runtime.create(core=CksCoreAdapter(), storage=InMemoryStorage())
    try:
        settings = GossipSettings(enabled=True, port=_free_port())
        handle = setup_gossip(runtime, settings)
        assert handle is not None

        session = await runtime.create_session(_structure("live"))
        assert session.session_id in handle.service.tracked_sessions

        await runtime.close_session(session.session_id)
        assert session.session_id not in handle.service.tracked_sessions
    finally:
        await runtime.aclose()


async def test_handle_start_stop_binds_and_releases_real_port():
    runtime = await Runtime.create(core=CksCoreAdapter(), storage=InMemoryStorage())
    try:
        settings = GossipSettings(enabled=True, port=_free_port())
        handle = setup_gossip(runtime, settings)
        assert handle is not None

        await handle.start()
        assert handle.server.running
        assert handle.service.running

        await handle.stop()
        assert not handle.server.running
        assert not handle.service.running
    finally:
        await runtime.aclose()


async def test_events_still_fire_for_regular_observability_when_gossip_enabled():
    """Sanity check that subscribing gossip's own SessionCreated/Closed
    handlers doesn't clobber other subscribers on the same EventBus."""
    runtime = await Runtime.create(core=CksCoreAdapter(), storage=InMemoryStorage())
    try:
        seen: list[str] = []
        runtime.events.subscribe(SessionCreated, lambda e: seen.append("created"))
        runtime.events.subscribe(SessionClosed, lambda e: seen.append("closed"))

        settings = GossipSettings(enabled=True, port=_free_port())
        handle = setup_gossip(runtime, settings)
        assert handle is not None

        session = await runtime.create_session(_structure("obj"))
        await runtime.close_session(session.session_id)

        assert seen == ["created", "closed"]
    finally:
        await runtime.aclose()
