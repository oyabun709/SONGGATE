"""Admin-only dependencies.

Two auth paths:
1. require_admin      — Clerk JWT, user must be in ADMIN_USER_IDS config list.
2. require_admin_secret — static X-Admin-Secret header (machine-to-machine).
"""

from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from config import settings
from dependencies.auth import get_current_user_id


async def require_admin(
    user_id: str = Depends(get_current_user_id),
) -> str:
    """Raise 403 unless the requesting Clerk user is in ADMIN_USER_IDS."""
    if not settings.admin_user_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Admin access not configured")
    allowed = {uid.strip() for uid in settings.admin_user_ids.split(",") if uid.strip()}
    if user_id not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user_id


async def require_admin_secret(
    x_admin_secret: Optional[str] = Header(default=None),
) -> str:
    """Raise 403 unless X-Admin-Secret header matches ADMIN_SECRET env var."""
    if not settings.admin_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin secret not configured on this server",
        )
    if not x_admin_secret or x_admin_secret.strip() != settings.admin_secret.strip():
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Invalid admin secret")
    return "admin_secret_user"
