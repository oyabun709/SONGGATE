"""
Stripe billing service.

Handles customer/subscription lifecycle, metered usage reporting,
checkout and portal session creation, and invoice retrieval.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from config import settings
from models.organization import Organization, OrgTier

logger = logging.getLogger(__name__)

# Price ID → tier mapping (populated from settings at call time)
def _price_to_tier() -> dict[str, OrgTier]:
    return {
        settings.stripe_starter_price_id:    OrgTier.starter,
        settings.stripe_pro_price_id:         OrgTier.pro,
        settings.stripe_enterprise_price_id:  OrgTier.enterprise,
    }


def _stripe():
    """Lazy Stripe client so import doesn't fail if key is absent."""
    import stripe
    stripe.api_key = settings.stripe_secret_key
    return stripe


# ─────────────────────────────────────────────────────────────────────────────
# Customer
# ─────────────────────────────────────────────────────────────────────────────

async def get_or_create_customer(org: Organization) -> str:
    """
    Return the Stripe customer ID for this org, creating one if it doesn't exist.
    Caller is responsible for persisting org.stripe_customer_id afterward.
    """
    if org.stripe_customer_id:
        return org.stripe_customer_id

    stripe = _stripe()
    loop = __import__("asyncio").get_event_loop()
    customer = await loop.run_in_executor(
        None,
        lambda: stripe.Customer.create(
            name=org.name,
            metadata={"ropqa_org_id": str(org.id), "clerk_org_id": org.clerk_org_id},
        ),
    )
    org.stripe_customer_id = customer["id"]
    return customer["id"]


# ─────────────────────────────────────────────────────────────────────────────
# Checkout & portal
# ─────────────────────────────────────────────────────────────────────────────

async def create_checkout_session(
    org: Organization,
    price_id: str,
) -> str:
    """Create a Stripe Checkout Session and return its URL."""
    stripe = _stripe()
    customer_id = await get_or_create_customer(org)

    loop = __import__("asyncio").get_event_loop()
    session = await loop.run_in_executor(
        None,
        lambda: stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{settings.frontend_url}/billing?checkout=success",
            cancel_url=f"{settings.frontend_url}/billing?checkout=canceled",
            metadata={"ropqa_org_id": str(org.id)},
            subscription_data={
                "metadata": {"ropqa_org_id": str(org.id)},
            },
        ),
    )
    return session["url"]


async def create_portal_session(org: Organization) -> str:
    """Create a Stripe Customer Portal Session and return its URL."""
    stripe = _stripe()
    customer_id = await get_or_create_customer(org)

    loop = __import__("asyncio").get_event_loop()
    session = await loop.run_in_executor(
        None,
        lambda: stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{settings.frontend_url}/billing",
        ),
    )
    return session["url"]


# ─────────────────────────────────────────────────────────────────────────────
# Invoices
# ─────────────────────────────────────────────────────────────────────────────

async def list_invoices(org: Organization, limit: int = 24) -> list[dict[str, Any]]:
    """Return recent invoices for the org's Stripe customer."""
    if not org.stripe_customer_id:
        return []

    stripe = _stripe()
    loop = __import__("asyncio").get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: stripe.Invoice.list(customer=org.stripe_customer_id, limit=limit),
    )
    return [
        {
            "id":          inv["id"],
            "number":      inv.get("number"),
            "status":      inv["status"],
            "amount_paid": inv["amount_paid"],       # cents
            "currency":    inv["currency"],
            "period_start": inv.get("period_start"), # unix timestamp
            "period_end":   inv.get("period_end"),
            "invoice_pdf":  inv.get("invoice_pdf"),
            "hosted_invoice_url": inv.get("hosted_invoice_url"),
        }
        for inv in result.get("data", [])
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Usage reporting (metered billing)
# ─────────────────────────────────────────────────────────────────────────────

async def report_usage(org: Organization, quantity: int = 1) -> None:
    """
    Report scan usage to Stripe for metered pricing items.
    No-ops if the org has no subscription item ID (Starter flat-rate).
    """
    if not org.stripe_subscription_item_id:
        return
    if org.tier == OrgTier.starter:
        return  # Starter is flat-rate, nothing to report

    stripe = _stripe()
    loop = __import__("asyncio").get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            lambda: stripe.SubscriptionItem.create_usage_record(
                org.stripe_subscription_item_id,
                quantity=quantity,
                action="increment",
            ),
        )
    except Exception:
        logger.warning(
            "Failed to report Stripe usage for org %s", org.id, exc_info=True
        )


# ─────────────────────────────────────────────────────────────────────────────
# Subscription sync (called from webhook handler)
# ─────────────────────────────────────────────────────────────────────────────

def apply_subscription_to_org(org: Organization, subscription: dict) -> None:
    """
    Update org fields from a Stripe Subscription object.
    Determines tier from the first price ID on the subscription.
    """
    org.stripe_subscription_id     = subscription["id"]
    org.stripe_subscription_status = subscription["status"]

    items = subscription.get("items", {}).get("data", [])
    if items:
        item = items[0]
        org.stripe_price_id             = item["price"]["id"]
        org.stripe_subscription_item_id = item["id"]

        tier = _price_to_tier().get(item["price"]["id"])
        if tier:
            org.tier = tier

    period = subscription.get("current_period_start")
    if period:
        org.current_period_start = datetime.fromtimestamp(period, tz=timezone.utc)
    period = subscription.get("current_period_end")
    if period:
        org.current_period_end = datetime.fromtimestamp(period, tz=timezone.utc)


def tier_for_price(price_id: str) -> OrgTier | None:
    return _price_to_tier().get(price_id)
