"""Shared HTTP layer.

Cross-cutting concerns (timeouts, retries, rate limiting) live here once so every
client inherits identical, well-behaved networking instead of each re-inventing it.
"""

from __future__ import annotations

import threading
import time

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger(__name__)

_TIMEOUT = httpx.Timeout(30.0)
_HEADERS = {"User-Agent": "NeoWatch/0.1 (NEO research agent)"}


def get_async_client() -> httpx.AsyncClient:
    """Return a configured async HTTP client (30s timeout, identifying UA).

    Callers should use it as an async context manager so connections are closed.
    """
    # follow_redirects: several of these APIs 301 from http->https or to a
    # canonical path; following them keeps the clients robust to that.
    return httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True)


# Reusable retry policy: 3 attempts, exponential backoff (1s, 2s, capped 4s),
# only for transient transport errors and 5xx-style HTTP errors. ``reraise``
# means the *original* exception surfaces after the final failure, not a
# tenacity wrapper — easier to handle upstream.
retry_external = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    reraise=True,
)


class NasaRateLimiter:
    """Tracks NASA API calls within a rolling hour and warns near the cap.

    NASA's documented limit is 1000 requests/hour per key; we warn at 900 to
    leave headroom for retries. The same key is shared by every NASA-backed
    client (NeoWs, APOD, DONKI), so this counter is process-wide and
    thread-safe — concurrent agents must not each keep a private tally.
    """

    def __init__(self, warn_threshold: int = 900) -> None:
        self._warn_threshold = warn_threshold
        self._timestamps: list[float] = []
        self._lock = threading.Lock()

    def record(self) -> None:
        """Register one call and warn (once it crosses the threshold)."""
        now = time.monotonic()
        with self._lock:
            self._timestamps = [t for t in self._timestamps if t > now - 3600]
            self._timestamps.append(now)
            count = len(self._timestamps)
        if count >= self._warn_threshold:
            logger.warning("nasa.rate_limit.near_cap", count=count, threshold=self._warn_threshold)

    @property
    def count(self) -> int:
        """Number of calls recorded in the last hour."""
        now = time.monotonic()
        with self._lock:
            self._timestamps = [t for t in self._timestamps if t > now - 3600]
            return len(self._timestamps)
