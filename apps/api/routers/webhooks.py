"""
Clerk webhook handler.

Register this endpoint in the Clerk Dashboard under
  Webhooks → Add Endpoint → https://<your-domain>/webhooks/clerk

Events to subscribe to:
  - organization.created
  - organization.updated
  - organization.deleted

Set the signing secret as CLERK_WEBHOOK_SECRET in your environment.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from svix.webhooks import Webhook, WebhookVerificationError

from config import settings
from database import get_db
from models.organization import Organization, OrgTier

logger = logging.getLogger(__name__)

router = APIRouter()


def _svix_headers(request: Request) -> dict[str, str]:
    return {
        "svix-id": request.headers.get("svix-id", ""),
        "svix-timestamp": request.headers.get("svix-timestamp", ""),
        "svix-signature": request.headers.get("svix-signature", ""),
    }


def _verify_payload(raw_body: bytes, headers: dict[str, str]) -> dict:
    if not settings.clerk_webhook_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CLERK_WEBHOOK_SECRET is not configured",
        )
    wh = Webhook(settings.clerk_webhook_secret)
    try:
        return wh.verify(raw_body, headers)
    except WebhookVerificationError as exc:
        logger.warning("Clerk webhook verification failed: %s", exc)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature",
        )


@router.post("/clerk", status_code=status.HTTP_200_OK)
async def clerk_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    raw_body = await request.body()
    event = _verify_payload(raw_body, _svix_headers(request))

    event_type: str = event.get("type", "")
    data: dict = event.get("data", {})

    logger.info("Received Clerk webhook: %s", event_type)

    if event_type == "organization.created":
        await _handle_org_created(data, db)
    elif event_type == "organization.updated":
        await _handle_org_updated(data, db)
    elif event_type == "organization.deleted":
        await _handle_org_deleted(data, db)
    else:
        logger.debug("Unhandled Clerk event type: %s", event_type)

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

async def _handle_org_created(data: dict, db: AsyncSession) -> None:
    clerk_org_id: str = data["id"]
    name: str = data.get("name", clerk_org_id)

    # Idempotent — skip if org already exists (on-demand creation may have raced)
    existing = await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    if existing:
        logger.info("Org %s already exists — skipping creation", clerk_org_id)
        return

    org = Organization(
        clerk_org_id=clerk_org_id,
        name=name,
        tier=OrgTier.starter,
        settings={},
    )
    db.add(org)
    await db.commit()
    logger.info("Created org %s (%s)", clerk_org_id, name)


async def _handle_org_updated(data: dict, db: AsyncSession) -> None:
    clerk_org_id: str = data["id"]
    name: str | None = data.get("name")

    org = await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    if not org:
        logger.warning("Received org.updated for unknown org %s", clerk_org_id)
        return

    if name:
        org.name = name
    await db.commit()
    logger.info("Updated org %s", clerk_org_id)


async def _handle_org_deleted(data: dict, db: AsyncSession) -> None:
    clerk_org_id: str = data["id"]

    org = await db.scalar(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id)
    )
    if org:
        await db.delete(org)
        await db.commit()
        logger.info("Deleted org %s", clerk_org_id)
