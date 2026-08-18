"""Tests for ``cks_mcp.llm.retry.call_with_retry``."""
from __future__ import annotations

import urllib.error

import pytest

from cks_mcp.llm.retry import call_with_retry


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://example.com", code, "err", {}, None)


def test_succeeds_first_try_no_retry():
    calls = {"n": 0}
    sleeps: list[float] = []

    def op():
        calls["n"] += 1
        return "ok"

    result = call_with_retry(op, sleep=sleeps.append)
    assert result == "ok"
    assert calls["n"] == 1
    assert sleeps == []


def test_429_then_success_retries_once():
    attempts = {"n": 0}
    sleeps: list[float] = []

    def op():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _http_error(429)
        return "recovered"

    result = call_with_retry(op, max_attempts=3, sleep=sleeps.append)
    assert result == "recovered"
    assert attempts["n"] == 2
    assert len(sleeps) == 1
    assert sleeps[0] > 0


def test_529_is_retryable():
    attempts = {"n": 0}

    def op():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _http_error(529)
        return "ok"

    assert call_with_retry(op, max_attempts=3, sleep=lambda _: None) == "ok"
    assert attempts["n"] == 2


def test_connection_error_is_retryable():
    attempts = {"n": 0}

    def op():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise urllib.error.URLError("connection refused")
        return "ok"

    assert call_with_retry(op, max_attempts=3, sleep=lambda _: None) == "ok"
    assert attempts["n"] == 2


def test_max_attempts_reached_raises_last_error():
    attempts = {"n": 0}

    def op():
        attempts["n"] += 1
        raise _http_error(429)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        call_with_retry(op, max_attempts=3, sleep=lambda _: None)

    assert exc_info.value.code == 429
    assert attempts["n"] == 3  # exhausted all attempts, no more, no fewer


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_non_retryable_http_status_raises_immediately(code):
    attempts = {"n": 0}
    sleeps: list[float] = []

    def op():
        attempts["n"] += 1
        raise _http_error(code)

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        call_with_retry(op, max_attempts=5, sleep=sleeps.append)

    assert exc_info.value.code == code
    assert attempts["n"] == 1  # never retried
    assert sleeps == []


def test_backoff_grows_exponentially_and_is_capped():
    attempts = {"n": 0}
    sleeps: list[float] = []

    def op():
        attempts["n"] += 1
        raise _http_error(429)

    with pytest.raises(urllib.error.HTTPError):
        call_with_retry(
            op,
            max_attempts=5,
            base_delay=1.0,
            max_delay=3.0,
            sleep=sleeps.append,
        )

    # 4 retries recorded (5 attempts total, last one doesn't sleep).
    assert len(sleeps) == 4
    # Every delay respects the cap (base_delay * 2**(n-1), jittered up
    # to 1.5x, then capped at max_delay * 1.5 -- jitter is applied
    # after the min(), so bound generously).
    for delay in sleeps:
        assert 0 < delay <= 3.0 * 1.5


def test_non_network_exception_not_caught():
    def op():
        raise ValueError("not an HTTP error at all")

    with pytest.raises(ValueError):
        call_with_retry(op, sleep=lambda _: None)
