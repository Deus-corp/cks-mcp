"""
Deterministic, no-network-I/O filtering for enrichment candidate URLs.

Two independent gates, both applied before an enrichment candidate is
worth spending an ``ingest_document`` call on:

- ``is_low_value_enrichment_url``: structural URL patterns that are
  almost never useful as *content* (login/auth pages, status pages,
  legal boilerplate) regardless of what site they're on.
- ``EnrichmentPolicy``: an operator-configured domain/prefix allow-
  or-block list, for deployments that want to restrict (or widen)
  which external hosts the agent is allowed to fetch from at all.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

LOW_VALUE_DOMAINS = frozenset(
    {
        "githubstatus.com",
        "www.githubstatus.com",
        "statuspage.io",
    }
)

LOW_VALUE_DOMAIN_SUFFIXES = (".statuspage.io",)

LOW_VALUE_PATH_MARKERS = frozenset(
    {
        "account",
        "accounts",
        "auth",
        "authorize",
        "callback",
        "contact",
        "cookie",
        "cookies",
        "donate",
        "login",
        "logout",
        "oauth",
        "privacy",
        "signin",
        "signup",
        "status",
        "subscribe",
        "subscription",
        "subscriptions",
        "support",
        "terms",
    }
)

LOW_VALUE_QUERY_KEYS = frozenset(
    {
        "client_id",
        "redirect_uri",
        "scope",
        "state",
        "utm_campaign",
        "utm_content",
        "utm_medium",
        "utm_source",
        "utm_term",
    }
)

LOW_VALUE_EXACT_PATHS = frozenset(
    {
        "/",
        "/about",
        "/community",
        "/contact",
        "/privacy",
        "/security",
        "/support",
        "/terms",
    }
)


def _domain(url: str) -> str:
    return urlparse(str(url or "")).netloc.lower().split("@")[-1]


def _path_parts(url: str) -> list[str]:
    parsed = urlparse(str(url or ""))
    return [p.strip().lower() for p in parsed.path.strip("/").split("/") if p.strip()]


def is_low_value_enrichment_url(url: str) -> bool:
    """
    True when ``url`` is almost never worth an ``ingest_document`` call
    for enrichment purposes -- a login wall, a status page, a legal/
    boilerplate page, and so on -- regardless of which domain it's on.
    Purely structural: does not fetch anything.
    """
    raw = str(url or "").strip()
    if not raw:
        return True

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        return True

    domain = _domain(raw)
    path = (parsed.path or "/").rstrip("/") or "/"
    parts = _path_parts(raw)
    query = parse_qs(parsed.query)

    if domain in LOW_VALUE_DOMAINS:
        return True
    if any(domain.endswith(suffix) for suffix in LOW_VALUE_DOMAIN_SUFFIXES):
        return True
    if path in LOW_VALUE_EXACT_PATHS:
        return True
    return any(part in LOW_VALUE_PATH_MARKERS for part in parts) or any(
        key.lower() in LOW_VALUE_QUERY_KEYS for key in query
    )


@dataclass(slots=True)
class EnrichmentPolicy:
    """
    Operator-configured allow/block policy for which external hosts the
    Enrichment Agent may fetch from. Independent of, and applied after,
    ``is_low_value_enrichment_url`` -- a URL can pass the structural
    check and still be blocked here (e.g. an operator that wants to
    restrict enrichment to a specific allowlist of trusted domains).
    """

    allow_domains: list[str] = field(default_factory=list)
    block_domains: list[str] = field(default_factory=list)
    allow_url_prefixes: list[str] = field(default_factory=list)
    block_url_prefixes: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> EnrichmentPolicy:
        def split_csv(name: str) -> list[str]:
            raw = os.environ.get(name, "")
            return [part.strip().lower() for part in raw.split(",") if part.strip()]

        return cls(
            allow_domains=split_csv("CKS_ENRICHMENT_ALLOW_DOMAINS"),
            block_domains=split_csv("CKS_ENRICHMENT_BLOCK_DOMAINS"),
            allow_url_prefixes=split_csv("CKS_ENRICHMENT_ALLOW_URL_PREFIXES"),
            block_url_prefixes=split_csv("CKS_ENRICHMENT_BLOCK_URL_PREFIXES"),
        )

    def domain_allowed(self, domain: str) -> bool:
        domain = (domain or "").lower()
        if not domain:
            return False
        if self.allow_domains and not any(
            domain == d or domain.endswith("." + d) for d in self.allow_domains
        ):
            return False
        return not any(domain == d or domain.endswith("." + d) for d in self.block_domains)

    def url_allowed(self, url: str) -> bool:
        if self.allow_url_prefixes and not any(
            url.startswith(prefix) for prefix in self.allow_url_prefixes
        ):
            return False
        return not any(url.startswith(prefix) for prefix in self.block_url_prefixes)

    def candidate_allowed(self, url: str) -> bool:
        """Combined check: structural low-value filter + domain/prefix policy."""
        if is_low_value_enrichment_url(url):
            return False
        if not self.url_allowed(url):
            return False
        return self.domain_allowed(_domain(url))