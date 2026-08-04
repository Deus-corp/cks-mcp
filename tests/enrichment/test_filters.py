from __future__ import annotations

from cks_mcp.enrichment.filters import EnrichmentPolicy, is_low_value_enrichment_url


def test_low_value_login_path():
    assert is_low_value_enrichment_url("https://example.com/login") is True


def test_low_value_root_path():
    assert is_low_value_enrichment_url("https://example.com/") is True


def test_low_value_status_domain():
    assert is_low_value_enrichment_url("https://www.githubstatus.com/incidents/abc") is True


def test_low_value_tracking_query_key():
    assert is_low_value_enrichment_url("https://example.com/page?utm_source=x") is True


def test_genuine_article_is_not_low_value():
    assert is_low_value_enrichment_url("https://en.wikipedia.org/wiki/Python_(programming_language)") is False


def test_non_http_scheme_is_low_value():
    assert is_low_value_enrichment_url("ftp://example.com/file") is True


def test_empty_url_is_low_value():
    assert is_low_value_enrichment_url("") is True


def test_policy_default_allows_everything_not_blocked():
    policy = EnrichmentPolicy()
    assert policy.candidate_allowed("https://arxiv.org/abs/1234.5678") is True


def test_policy_block_domain():
    policy = EnrichmentPolicy(block_domains=["arxiv.org"])
    assert policy.domain_allowed("arxiv.org") is False
    assert policy.domain_allowed("export.arxiv.org") is False  # subdomain of blocked
    assert policy.candidate_allowed("https://arxiv.org/abs/1234.5678") is False


def test_policy_allowlist_excludes_everything_else():
    policy = EnrichmentPolicy(allow_domains=["wikipedia.org"])
    assert policy.domain_allowed("en.wikipedia.org") is True
    assert policy.domain_allowed("arxiv.org") is False


def test_policy_from_env(monkeypatch):
    monkeypatch.setenv("CKS_ENRICHMENT_BLOCK_DOMAINS", "spam.example.com, ads.example.com")
    policy = EnrichmentPolicy.from_env()
    assert policy.block_domains == ["spam.example.com", "ads.example.com"]
    assert policy.domain_allowed("spam.example.com") is False


def test_policy_candidate_allowed_still_applies_low_value_filter():
    """A permissive policy must not bypass the structural low-value filter."""
    policy = EnrichmentPolicy(allow_domains=["example.com"])
    assert policy.candidate_allowed("https://example.com/login") is False