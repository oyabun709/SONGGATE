"""
Webhook endpoint management (authenticated dashboard routes).

POST   /settings/webhooks         — register a new endpoint
GET    /settings/webhooks         — list all endpoints for this org
DELETE /settings/webhooks/{id}    — remove an endpoint
GET    /settings/webhooks/{id}/deliveries — delivery log for one endpoint
POST   /settings/webhooks/{id}/test       — fire a test.ping event
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies.auth import get_current_org
from models.organization import Organization
from services.webhooks import generate_webhook_secret, deliver_event

router = APIRouter(prefix="/settings/webhooks", tags=["webhook-settings"])


class WebhookEndpointCreate(BaseModel):
    url: HttpUrl
    description: str | None = Field(None, max_length=255)
    events: list[str] | None = Field(
        None,
        description="Event types to subscribe to. Omit for all events.",
        examples=[["scan.complete", "bulk.complete"]],
    )


class WebhookEndpointRead(BaseModel):
    id: str
    url: str
    description: str | None
    events: list[str] | None
    active: bool
    created_at: str


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_webhook_endpoint(
    body: WebhookEndpointCreate,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    """Register a new webhook endpoint. Returns the signing secret — store it securely."""
    ep_id = str(uuid.uuid4())
    secret = generate_webhook_secret()
    now = datetime.now(timezone.utc).isoformat()

    await db.execute(
        text("""
            INSERT INTO webhook_endpoints
                (id, org_id, url, description, secret, events, active, created_at, updated_at)
            VALUES
                (:id, :org_id, :url, :description, :secret, :events, true, :now, :now)
        """),
        {
            "id":          ep_id,
            "org_id":      str(org.id),
            "url":         str(body.url),
            "description": body.description,
            "secret":      secret,
            "events":      body.events,
            "now":         now,
        },
    )
    await db.commit()

    return {
        "id":          ep_id,
        "url":         str(body.url),
        "description": body.description,
        "events":      body.events,
        "active":      True,
        "created_at":  now,
        # Secret returned ONCE on creation only
        "secret": secret,
        "signing_hint": (
            "Verify incoming requests by computing HMAC-SHA256(secret, body) "
            "and comparing with the X-SONGGATE-Signature header (sha256=<hex>). "
            "This secret will not be shown again."
        ),
    }


@router.get("")
async def list_webhook_endpoints(
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    rows = await db.execute(
        text("""
            SELECT id, url, description, events, active, created_at
            FROM webhook_endpoints
            WHERE org_id = :org_id
            ORDER BY created_at DESC
        """),
        {"org_id": str(org.id)},
    )
    return [
        {
            "id":          str(r["id"]),
            "url":         r["url"],
            "description": r["description"],
            "events":      r["events"],
            "active":      r["active"],
            "created_at":  r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows.mappings().all()
    ]


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook_endpoint(
    endpoint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    result = await db.execute(
        text("SELECT id FROM webhook_endpoints WHERE id = :id AND org_id = :org_id"),
        {"id": str(endpoint_id), "org_id": str(org.id)},
    )
    if not result.first():
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    await db.execute(
        text("DELETE FROM webhook_endpoints WHERE id = :id"),
        {"id": str(endpoint_id)},
    )
    await db.commit()


@router.get("/{endpoint_id}/deliveries")
async def get_webhook_deliveries(
    endpoint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    # Verify ownership
    ep = await db.execute(
        text("SELECT id FROM webhook_endpoints WHERE id = :id AND org_id = :org_id"),
        {"id": str(endpoint_id), "org_id": str(org.id)},
    )
    if not ep.first():
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")

    rows = await db.execute(
        text("""
            SELECT id, event_type, status_code, status, attempt, error,
                   delivered_at, created_at
            FROM webhook_deliveries
            WHERE endpoint_id = :ep_id
            ORDER BY created_at DESC
            LIMIT 50
        """),
        {"ep_id": str(endpoint_id)},
    )
    return [
        {
            "id":           str(r["id"]),
            "event_type":   r["event_type"],
            "status_code":  r["status_code"],
            "status":       r["status"],
            "attempt":      r["attempt"],
            "error":        r["error"],
            "delivered_at": r["delivered_at"].isoformat() if r["delivered_at"] else None,
            "created_at":   r["created_at"].isoformat()   if r["created_at"]   else None,
        }
        for r in rows.mappings().all()
    ]


@router.post("/{endpoint_id}/test", status_code=status.HTTP_202_ACCEPTED)
async def test_webhook_endpoint(
    endpoint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    org: Organization = Depends(get_current_org),
):
    ep = await db.execute(
        text("SELECT id FROM webhook_endpoints WHERE id = :id AND org_id = :org_id AND active = true"),
        {"id": str(endpoint_id), "org_id": str(org.id)},
    )
    if not ep.first():
        raise HTTPException(status_code=404, detail="Webhook endpoint not found or inactive")

    await deliver_event(
        db=db,
        org_id=str(org.id),
        event_type="test.ping",
        payload={
            "message": "SONGGATE webhook test — delivery confirmed",
            "endpoint_id": str(endpoint_id),
        },
    )
    return {"status": "queued", "event": "test.ping"}
