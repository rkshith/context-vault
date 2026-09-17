"""Minimal in-memory sliding-window rate limiter.

No extra dependency. Per-process state is fine for a single-backend deployment;
replace with Redis when scaling horizontally.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

_hits: dict[str, deque[float]] = defaultdict(deque)


def _purge() -> None:
    for key in [k for k, bucket in _hits.items() if not bucket]:
        del _hits[key]


def rate_limit(max_calls: int, window_seconds: int):
    async def dependency(request: Request) -> None:
        now = time.monotonic()
        key = f"{request.client.host if request.client else 'unknown'}:{request.url.path}"
        bucket = _hits[key]
        while bucket and bucket[0] <= now - window_seconds:
            bucket.popleft()
        if len(bucket) >= max_calls:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests, please slow down",
            )
        bucket.append(now)
        if len(_hits) > 10000:
            _purge()

    return dependency


login_limit = rate_limit(max_calls=10, window_seconds=60)
chat_limit = rate_limit(max_calls=30, window_seconds=60)
