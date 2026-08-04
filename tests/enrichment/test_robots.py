from __future__ import annotations

from dataclasses import dataclass

import pytest

from cks_mcp.enrichment import robots as robots_module


@pytest.fixture(autouse=True)
def _reset_cache():
    robots_module.reset_robots_cache()
    yield
    robots_module.reset_robots_cache()


@dataclass
class _FakeResponse:
    status_code: int
    text: str


def test_disallowed_path_is_blocked(monkeypatch):
    def fake_safe_request(url, **kwargs):
        return _FakeResponse(200, "User-agent: *\nDisallow: /private/\n")

    monkeypatch.setattr(robots_module, "_safe_request", fake_safe_request)
    assert robots_module.robots_allows("https://example.com/private/page") is False
    assert robots_module.robots_allows("https://example.com/public/page") is True


def test_missing_robots_txt_fails_open(monkeypatch):
    def fake_safe_request(url, **kwargs):
        return _FakeResponse(404, "")

    monkeypatch.setattr(robots_module, "_safe_request", fake_safe_request)
    assert robots_module.robots_allows("https://example.com/anything") is True


def test_unreachable_robots_txt_fails_open(monkeypatch):
    def fake_safe_request(url, **kwargs):
        return None

    monkeypatch.setattr(robots_module, "_safe_request", fake_safe_request)
    assert robots_module.robots_allows("https://example.com/anything") is True


def test_exception_fetching_robots_txt_fails_open(monkeypatch):
    def fake_safe_request(url, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(robots_module, "_safe_request", fake_safe_request)
    assert robots_module.robots_allows("https://example.com/anything") is True


def test_non_http_url_fails_open():
    assert robots_module.robots_allows("ftp://example.com/file") is True


def test_result_is_cached_per_domain(monkeypatch):
    calls = []

    def fake_safe_request(url, **kwargs):
        calls.append(url)
        return _FakeResponse(200, "User-agent: *\nDisallow: /private/\n")

    monkeypatch.setattr(robots_module, "_safe_request", fake_safe_request)
    robots_module.robots_allows("https://example.com/a")
    robots_module.robots_allows("https://example.com/b")
    assert len(calls) == 1  # second call hit the cache, not a second fetch