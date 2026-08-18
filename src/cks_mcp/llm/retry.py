"""
Shared retry/backoff helper for LLM provider HTTP calls
(``cks_mcp.llm_providers``).

All of ``call_anthropic``/``call_ollama``/``call_openai_compatible_*``
are synchronous, blocking ``urllib`` calls (see ``llm_providers``'
module docstring for why), so this helper is synchronous too --
``time.sleep`` between attempts, no event loop involved. It is
intentionally tiny: it knows nothing about response bodies or
provider-specific error shapes, only "is this exception retryable"
and "how long to wait before trying again".

Retryable outcomes:
    * HTTP 429 (rate limited) and 529 (Anthropic-specific overloaded)
    * Network-level failures with no HTTP status at all (DNS failure,
      connection refused, timeout) -- i.e. ``urllib.error.URLError``
      that is *not* an ``HTTPError`` (``HTTPError`` subclasses
      ``URLError`` and always carries a ``.code``, so it is checked
      first and handled on its own terms).

Anything else (400, 401, 403, 404, a missing API key raised before
any request is even made, an unknown model, ...) is *not* retryable
and is re-raised on the first attempt, unchanged, so callers'
existing ``except HTTPError``/``except URLError`` blocks keep
producing the same descriptive ``RuntimeError`` messages they always
have.
"""

from __future__ import annotations

import logging
import random
import time
import urllib.error
from collections.abc import Callable

# HTTP status codes worth retrying: 429 (rate limited) and 529
# (Anthropic's "overloaded", https://docs.anthropic.com/en/api/errors).
RETRYABLE_HTTP_STATUS_CODES = frozenset({429, 529})

DEFAULT_MAX_ATTEMPTS = 4
DEFAULT_BASE_DELAY_SECONDS = 0.5
DEFAULT_MAX_DELAY_SECONDS = 8.0


class RetryExhausted(RuntimeError):
    """Raised when every retry attempt failed with a retryable error.

    Wraps the last underlying exception in ``__cause__`` (via ``raise
    ... from exc``) so callers/logs still see the original
    HTTPError/URLError detail.
    """


def call_with_retry[T](
    operation: Callable[[], T],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY_SECONDS,
    max_delay: float = DEFAULT_MAX_DELAY_SECONDS,
    retryable_status_codes: frozenset[int] = RETRYABLE_HTTP_STATUS_CODES,
    sleep: Callable[[float], None] = time.sleep,
    logger: logging.Logger | None = None,
    call_label: str = "LLM provider call",
) -> T:
    """Call ``operation()`` and return its result, retrying on
    transient failures with exponential backoff + full jitter.

    ``operation`` takes no arguments and should perform exactly one
    HTTP attempt (e.g. the ``urllib.request.urlopen(...)`` + response
    read/parse for one call) -- retrying re-invokes it from scratch,
    so it must be safe to run more than once (true for the read-only,
    single-shot completion calls this is used for).

    On the last attempt, a retryable error is re-raised as-is (not
    wrapped) so existing ``except HTTPError``/``except URLError``
    handling around the call site keeps working unchanged. Non-
    retryable errors (any other HTTPError status, or a non-network
    exception like a missing API key raised before ``operation`` is
    even called) always propagate on the first attempt.

    Backoff is ``min(max_delay, base_delay * 2 ** (attempt - 1))``,
    scaled by a random factor in ``[0.5, 1.5)`` ("full jitter" variant)
    so concurrent callers don't retry in lockstep. Never logs
    exception text verbatim -- only the HTTP status/exception class
    name and attempt count -- so a provider echoing request headers
    back in an error body can't leak a key into retry logs.
    """
    log = logger or logging.getLogger(__name__)
    attempt = 0

    while True:
        attempt += 1
        exc_name: str | None = None
        try:
            return operation()
        except urllib.error.HTTPError as exc:
            retryable = exc.code in retryable_status_codes
            if not retryable or attempt >= max_attempts:
                raise
            exc_name = type(exc).__name__
        except urllib.error.URLError as exc:
            # URLError without an HTTP status at all (connection
            # refused, DNS failure, timeout) -- HTTPError is handled
            # above since it subclasses URLError.
            if attempt >= max_attempts:
                raise
            exc_name = type(exc).__name__

        delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
        delay *= 0.5 + random.random()
        log.warning(
            "%s failed (attempt %d/%d, %s) -- retrying in %.2fs",
            call_label,
            attempt,
            max_attempts,
            exc_name,
            delay,
        )
        sleep(delay)
