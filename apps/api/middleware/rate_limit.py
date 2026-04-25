"""
Per-API-key rate limiting middleware.

Tier limits (requests per minute):
  Starter:    5
  Pro:       30
  Enterprise: 200

Uses an in-memory sliding-window counter keyed on the API key hash.
Falls back gracefully — if the key cannot be identified the request
is allowed through (the auth layer will reject it anyway).

Response headers on every API key request:
  X-RateLimit-Limit     — tier limit
  X-RateLimit-Remaining — remaining requests in the current window
  X-RateLimit-Reset     — Unix timestamp when the window resets

On 429:
  {
    "detail": {
      "code":    "rate_limit_exceeded",
      "message": "Rate limit exceeded. Upgrade your plan or wait N seconds.",
      "limit":   30,
      "reset_at": 1714000060
    }
  }
"""

from __future__ import annotations

import hashlib
import math
import time
from collections import deque
from threading import Lock
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from models.organization import OrgTier

# ── Tier limits (requests per minute) ────────────────────────────────────────

TIER_RATE_LIMIT: dict[str, int] = {
    OrgTier.starter:    5,
    OrgTier.pro:        30,
    OrgTier.enterprise: 200,
}
_DEFAULT_LIMIT = 5
_WINDOW_SECONDS = 60

# ── In-memory sliding window store ───────────────────────────────────────────
# { key_hash_8: deque[timestamp_float] }
_buckets: dict[str, deque] = {}
_lock = Lock()

_PUBLIC_API_PREFIX = "/api/v1/"


def _extract_key_hash(authorization: str) -> str | None:
    """Return the first 8 chars of SHA-256(raw_key), or None."""
    if not authorization:
        return None
    scheme, _, raw_key = authorization.partition(" ")
    if scheme.lower() != "bearer" or not raw_key:
        return None
    return hashlib.sha256(raw_key.encode()).hexdigest()[:8]


def _rate_limit_check(key_id: str, limit: int) -> tuple[bool, int, int]:
    """
    Sliding window check.

    Returns (allowed, remaining, reset_ts).
    `allowed` is False when the request should be rejected.
    """
    now = time.time()
    window_start = now - _WINDOW_SECONDS

    with _lock:
        bucket = _buckets.setdefault(key_id, deque())
        # Evict timestamps outside the window
        while bucket and bucket[0] < window_start:
            bucket.popleft()

        count = len(bucket)
        if count >= limit:
            # Window resets when the oldest request expires
            reset_ts = math.ceil(bucket[0] + _WINDOW_SECONDS)
            return False, 0, reset_ts

        bucket.append(now)
        remaining = limit - len(bucket)
        reset_ts = math.ceil(now + _WINDOW_SECONDS)
        return True, remaining, reset_ts


async def _record_usage_event(
    org_id: str,
    api_key_id: str | None,
    endpoint: str,
    method: str,
    status_code: int,
    latency_ms: int,
) -> None:
    """Insert one row into api_usage_events (fire-and-forget)."""
    try:
        from database import AsyncSessionLocal
        from sqlalchemy import text as _text
        async with AsyncSessionLocal() as db:
            await db.execute(
                _text("""
                    INSERT INTO api_usage_events
                        (id, org_id, api_key_id, endpoint, method, status_code, latency_ms, created_at)
                    VALUES
                        (gen_random_uuid(), :org_id, :key_id, :endpoint, :method,
                         :status_code, :latency_ms, NOW())
                """),
                {
                    "org_id":      org_id,
                    "key_id":      api_key_id,
                    "endpoint":    endpoint,
                    "method":      method,
                    "status_code": status_code,
                    "latency_ms":  latency_ms,
                },
            )
            await db.commit()
    except Exception:
        pass  # never block a response for analytics


class APIKeyRateLimitMiddleware(BaseHTTPMiddleware):
    """
    Attach to the FastAPI app to rate-limit requests to /api/v1/ endpoints.

    Tier is resolved lazily from the JWT claim injected by _get_api_key_org.
    When the tier is not yet known (early in the pipeline) the default
    Starter limit applies.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        path = request.url.path

        # Only rate-limit the public API surface
        if not path.startswith(_PUBLIC_API_PREFIX):
            return await call_next(request)

        authorization = request.headers.get("authorization", "")
        key_hash = _extract_key_hash(authorization)

        # No key → let auth middleware reject it; don't count
        if not key_hash:
            return await call_next(request)

        # Resolve tier from request state (set by auth dep) or default
        tier: str = getattr(request.state, "org_tier", OrgTier.starter)
        limit = TIER_RATE_LIMIT.get(tier, _DEFAULT_LIMIT)

        allowed, remaining, reset_ts = _rate_limit_check(key_hash, limit)

        if not allowed:
            wait = reset_ts - int(time.time())
            return JSONResponse(
                status_code=429,
                headers={
                    "X-RateLimit-Limit":     str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset":     str(reset_ts),
                    "Retry-After":           str(max(1, wait)),
                },
                content={
                    "detail": {
                        "code":    "rate_limit_exceeded",
                        "message": (
                            f"Rate limit exceeded. "
                            f"Your plan allows {limit} requests/min. "
                            f"Upgrade or wait {max(1, wait)} second(s)."
                        ),
                        "limit":    limit,
                        "reset_at": reset_ts,
                    }
                },
            )

        t0 = time.time()
        response = await call_next(request)
        latency_ms = int((time.time() - t0) * 1000)

        response.headers["X-RateLimit-Limit"]     = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"]     = str(reset_ts)

        # Record usage event (fire-and-forget; errors silently ignored)
        org_id_state: str | None = getattr(request.state, "org_id", None)
        key_id_state: str | None = getattr(request.state, "api_key_id", None)
        if org_id_state:
            import asyncio
            asyncio.create_task(_record_usage_event(
                org_id=org_id_state,
                api_key_id=key_id_state,
                endpoint=path,
                method=request.method,
                status_code=response.status_code,
                latency_ms=latency_ms,
            ))

        return response
