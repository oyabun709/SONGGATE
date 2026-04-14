"""
Clerk JWT verification and org resolution dependency.

Every protected route injects `get_current_org` to:
  1. Parse the Bearer token from the Authorization header.
  2. Verify the JWT signature against Clerk's JWKS endpoint.
  3. Extract the active org_id from the token claims.
  4. Return the matching Organization row, creating it on-demand if the
     webhook hasn't fired yet (safe fallback for new orgs).

JWKS keys are cached in-process with a 1-hour TTL to avoid hammering
Clerk on every request.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models.organization import Organization

# ---------------------------------------------------------------------------
# JWKS cache (module-level, shared across requests within the process)
# ---------------------------------------------------------------------------

_JWKS_TTL = 3600.0  # seconds

_jwks_keys: list[dict] = []
_jwks_expiry: float = 0.0


async def _get_jwks() -> list[dict]:
    """Return cached JWKS keys, refreshing from Clerk when stale."""
    global _jwks_keys, _jwks_expiry

    if time.monotonic() < _jwks_expiry and _jwks_keys:
        return _jwks_keys

    if not settings.clerk_jwks_url:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CLERK_JWKS_URL is not configured",
        )

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(settings.clerk_jwks_url)
        resp.raise_for_status()

    data = resp.json()
    _jwks_keys = data.get("keys", [])
    _jwks_expiry = time.monotonic() + _JWKS_TTL
    return _jwks_keys


# ---------------------------------------------------------------------------
# JWT verification
# ---------------------------------------------------------------------------

async def _verify_clerk_jwt(token: str) -> dict[str, Any]:
    """
    Verify a Clerk-issued JWT and return its claims.

    Clerk signs tokens with RS256.  We look up the matching JWK by `kid`
    from the cached JWKS and let python-jose handle the verification.
    """
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token header: {exc}")

    kid = header.get("kid")
    keys = await _get_jwks()

    matching_key = next((k for k in keys if k.get("kid") == kid), None)

    # If no match, try once more with a fresh JWKS (key rotation)
    if matching_key is None:
        global _jwks_expiry
        _jwks_expiry = 0.0
        keys = await _get_jwks()
        matching_key = next((k for k in keys if k.get("kid") == kid), None)

    if matching_key is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="JWT signing key not found in JWKS",
        )

    try:
        claims = jwt.decode(
            token,
            matching_key,
            algorithms=["RS256"],
            options={"verify_aud": False},  # Clerk JWTs omit standard aud
        )
    except JWTError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail=f"Token verification failed: {exc}",
        )

    return claims


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

async def get_current_org(
    authorization: str = Header(..., description="Bearer <clerk_session_token>"),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    """
    Resolve the active Clerk organization from the request JWT.

    Raises 401 if the token is missing, invalid, or carries no active org.
    """
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be 'Bearer <token>'",
        )

    claims = await _verify_clerk_jwt(token)

    clerk_org_id: str | None = claims.get("org_id")
    if not clerk_org_id:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="No active organization in token — select an org in the frontend",
        )

    # Look up the org by Clerk's org ID
    result = await db.execute(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    org = result.scalar_one_or_none()

    if org is None:
        # Webhook may not have fired yet — create the org on-demand as a safe
        # fallback.  The webhook handler will be a no-op if the row already exists.
        org_name: str = claims.get("org_slug") or clerk_org_id
        org = Organization(
            id=uuid.uuid4(),
            clerk_org_id=clerk_org_id,
            name=org_name,
        )
        db.add(org)
        try:
            await db.commit()
            await db.refresh(org)
        except Exception:
            await db.rollback()
            # Another request beat us to it — fetch the row that now exists
            result = await db.execute(
                select(Organization).where(Organization.clerk_org_id == clerk_org_id)
            )
            org = result.scalar_one()

    return org
