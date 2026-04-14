"""
Webhook handlers.

Clerk
─────
Register at: Clerk Dashboard → Webhooks → https://<domain>/webhooks/clerk
Events: organization.created, organization.updated, organization.deleted
Secret: CLERK_WEBHOOK_SECRET

Stripe
──────
Register at: Stripe Dashboard → Developers → Webhooks → https://<domain>/webhooks/stripe
Events:
  - checkout.session.completed
  - customer.subscription.updated
  - customer.subscription.deleted
  - invoice.payment_failed
Secret: STRIPE_WEBHOOK_SECRET
"""

import logging
from datetime import datetime, timezone

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
        # On-demand creation may have used the slug as a placeholder name.
        # Overwrite with the real display name from the webhook payload.
        if name and existing.name != name:
            existing.name = name
            await db.commit()
            logger.info("Org %s name corrected to '%s'", clerk_org_id, name)
        else:
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


# ─────────────────────────────────────────────────────────────────────────────
# Stripe webhook
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/stripe", status_code=status.HTTP_200_OK)
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Handle Stripe events.

    Stripe sends a `Stripe-Signature` header containing a HMAC-SHA256 signature
    that we verify against STRIPE_WEBHOOK_SECRET before trusting the payload.
    """
    raw_body = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not settings.stripe_webhook_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="STRIPE_WEBHOOK_SECRET is not configured",
        )

    try:
        import stripe
        stripe.api_key = settings.stripe_secret_key
        event = stripe.Webhook.construct_event(
            raw_body, sig_header, settings.stripe_webhook_secret
        )
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid payload")
    except stripe.SignatureVerificationError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid Stripe signature")

    event_type: str = event["type"]
    data: dict = event["data"]["object"]

    logger.info("Stripe webhook: %s  id=%s", event_type, event["id"])

    if event_type == "checkout.session.completed":
        await _stripe_checkout_completed(data, db)
    elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
        await _stripe_subscription_updated(data, db)
    elif event_type == "customer.subscription.deleted":
        await _stripe_subscription_deleted(data, db)
    elif event_type == "invoice.payment_failed":
        await _stripe_payment_failed(data, db)
    else:
        logger.debug("Unhandled Stripe event: %s", event_type)

    return {"status": "ok"}


async def _get_org_by_stripe_customer(
    db: AsyncSession, customer_id: str
) -> Organization | None:
    return await db.scalar(
        select(Organization).where(Organization.stripe_customer_id == customer_id)
    )


async def _stripe_checkout_completed(data: dict, db: AsyncSession) -> None:
    """
    Fired after a successful Checkout Session.
    The subscription object is embedded in the session — pull it and sync.
    """
    customer_id: str | None = data.get("customer")
    subscription_id: str | None = data.get("subscription")
    org_id_meta: str | None = (data.get("metadata") or {}).get("ropqa_org_id")

    # Resolve org
    org: Organization | None = None
    if org_id_meta:
        import uuid
        try:
            org = await db.scalar(
                select(Organization).where(Organization.id == uuid.UUID(org_id_meta))
            )
        except Exception:
            pass

    if org is None and customer_id:
        org = await _get_org_by_stripe_customer(db, customer_id)

    if org is None:
        logger.error("checkout.session.completed: could not find org for customer %s", customer_id)
        return

    # Persist customer ID in case it wasn't set yet
    if customer_id and not org.stripe_customer_id:
        org.stripe_customer_id = customer_id

    # Fetch the subscription object from Stripe for full details
    if subscription_id:
        import stripe
        stripe.api_key = settings.stripe_secret_key
        subscription = stripe.Subscription.retrieve(subscription_id)
        from services.billing import apply_subscription_to_org
        apply_subscription_to_org(org, subscription)
        # Reset scan counter for the new billing period
        org.scan_count_current_period = 0

    await db.commit()
    logger.info(
        "checkout.session.completed: org %s → tier=%s sub=%s",
        org.id, org.tier, org.stripe_subscription_id,
    )


async def _stripe_subscription_updated(data: dict, db: AsyncSession) -> None:
    """Sync subscription changes (plan upgrade/downgrade, renewal)."""
    customer_id: str = data.get("customer", "")
    org = await _get_org_by_stripe_customer(db, customer_id)
    if not org:
        logger.warning("subscription.updated: no org for customer %s", customer_id)
        return

    from services.billing import apply_subscription_to_org
    apply_subscription_to_org(org, data)

    # If the billing period rolled over, reset the scan counter
    if org.current_period_start:
        # Compare stored period start with what Stripe just sent
        new_start_ts = data.get("current_period_start")
        if new_start_ts:
            new_start = datetime.fromtimestamp(new_start_ts, tz=timezone.utc)
            stored = org.current_period_start
            if stored is None or new_start > stored:
                org.scan_count_current_period = 0

    await db.commit()
    logger.info(
        "subscription.updated: org %s tier=%s status=%s",
        org.id, org.tier, org.stripe_subscription_status,
    )


async def _stripe_subscription_deleted(data: dict, db: AsyncSession) -> None:
    """Downgrade org to Starter when subscription is canceled."""
    customer_id: str = data.get("customer", "")
    org = await _get_org_by_stripe_customer(db, customer_id)
    if not org:
        return

    org.stripe_subscription_status = "canceled"
    org.tier = OrgTier.starter
    org.stripe_subscription_id = None
    org.stripe_price_id = None
    org.stripe_subscription_item_id = None
    await db.commit()
    logger.info("subscription.deleted: org %s downgraded to Starter", org.id)


async def _stripe_payment_failed(data: dict, db: AsyncSession) -> None:
    """Mark subscription as past_due — gating middleware will block access."""
    customer_id: str = data.get("customer", "")
    org = await _get_org_by_stripe_customer(db, customer_id)
    if not org:
        return

    org.stripe_subscription_status = "past_due"
    await db.commit()
    logger.warning("invoice.payment_failed: org %s marked past_due", org.id)
