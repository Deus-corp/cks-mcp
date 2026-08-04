"""
robots.txt compliance for the Enrichment Agent.

Neither ``ingest_document`` nor ``verify_source`` currently check
robots.txt at all -- both are normally invoked directly by a human or
an LLM fetching one URL at a time, closer to "a browser fetching a page
a person asked for" than "a bot crawling a site". The Enrichment Agent
is different: it fetches URLs *unattended*, discovered by its own
search step rather than named by a person, so it needs to behave like
a well-behaved crawler and respect robots.txt -- this module is that
gate, checked before ``ingest_document`` is called on any enrichment
candidate.

Uses the same SSRF-safe ``_safe_request`` as ``ingest_document``/
``verify_source`` to fetch ``robots.txt`` itself, so the fetch used to
decide "am I allowed to fetch this" gets the same protection as every
other fetch in this codebase.
"""

from __future__ import annotations

import threading
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from cks_mcp.tools.verify_source.handler import _safe_request

_DEFAULT_USER_AGENT = "cks-enrichment-agent/1.0"

# domain -> RobotFileParser, process-local, never expires for the life
# of the process -- robots.txt changing mid-run is an acceptable risk
# for how infrequently this cache is populated (one entry per domain
# the agent has ever considered, not per fetch).
_CACHE: dict[str, RobotFileParser] = {}
_CACHE_LOCK = threading.Lock()


def _fetch_robots_txt(domain: str, scheme: str) -> str:
    robots_url = f"{scheme}://{domain}/robots.txt"
    try:
        resp = _safe_request(robots_url, method="GET", timeout=5)
    except Exception:  # noqa: BLE001 — best-effort robots.txt fetch
        return ""
    if resp is None or resp.status_code >= 400:
        return ""
    return resp.text or ""


def robots_allows(url: str, *, user_agent: str = _DEFAULT_USER_AGENT) -> bool:
    """
    True if ``user_agent`` is allowed to fetch ``url`` per that host's
    robots.txt. Fails open (returns True) if the domain can't be
    extracted, robots.txt can't be fetched, or fetching it raises --
    an unreachable/missing robots.txt is treated as "no restriction
    stated", the same convention ``RobotFileParser`` itself uses for a
    404. This is a synchronous, blocking call (matching ``_safe_request``
    itself) -- callers on an event loop should run it via
    ``asyncio.to_thread``, same as ``ingest_document`` does for its own
    fetch.
    """
    parsed = urlparse(str(url or ""))
    domain = parsed.netloc.lower()
    if not domain or parsed.scheme not in {"http", "https"}:
        return True

    with _CACHE_LOCK:
        parser = _CACHE.get(domain)

    if parser is None:
        robots_txt = _fetch_robots_txt(domain, parsed.scheme)
        parser = RobotFileParser()
        parser.parse(robots_txt.splitlines())
        with _CACHE_LOCK:
            _CACHE[domain] = parser

    try:
        return parser.can_fetch(user_agent, url)
    except Exception:  # noqa: BLE001 — best-effort robots.txt fetch
        # A parser that chokes on a malformed robots.txt shouldn't block
        # every fetch to that domain for the rest of the process.
        return True


def reset_robots_cache() -> None:
    """Clear the process-local robots.txt cache -- for tests only."""
    with _CACHE_LOCK:
        _CACHE.clear()