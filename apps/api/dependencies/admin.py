"""Admin-only dependency — checks that the requesting Clerk user is in
the ADMIN_USER_IDS list from config."""

from fastapi import Depends, HTTPException, status

from config import settings
from dependencies.auth import get_current_user_id


async def require_admin(
    user_id: str = Depends(get_current_user_id),
) -> str:
    """Raise 403 unless the requesting user is in ADMIN_USER_IDS."""
    if not settings.admin_user_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Admin access not configured")
    allowed = {uid.strip() for uid in settings.admin_user_ids.split(",") if uid.strip()}
    if user_id not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user_id
