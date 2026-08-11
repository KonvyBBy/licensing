"""Per-IP sliding-window rate limiter (in-process; fine for a single instance)."""

import os
import time
from collections import defaultdict, deque

# Set DISABLE_RATE_LIMIT=1 to bypass (used by the test suite).
DISABLED = os.environ.get("DISABLE_RATE_LIMIT") == "1"

# bucket: (window_seconds, max_requests)
LIMITS = {
    "admin:login": (60, 5),
    "admin:general": (60, 120),
    "client:activate": (60, 10),
    "client:verify": (60, 120),
}

_buckets: dict[str, deque] = defaultdict(deque)


def rate_limit(key: str, bucket: str) -> bool:
    """Return True if the request is allowed, False if it should be blocked."""
    if DISABLED:
        return True
    window, max_req = LIMITS[bucket]
    now = time.monotonic()
    dq = _buckets[key]
    while dq and now - dq[0] > window:
        dq.popleft()
    if len(dq) >= max_req:
        return False
    dq.append(now)
    return True
