"""
Tier-based feature gating dependencies.

Usage in a route:

    @router.post("/some-endpoint")
    async def my_endpoint(
        org: Organization = Depends(require_tier(OrgTier.pro)),
    ):
        ...

Or for scan limit enforcement:

    await check_scan_limit(org)
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status

from dependencies.auth import get_current_org
from models.organization import Organization, OrgTier, TIER_ORDER


# ─── Tier gate ────────────────────────────────────────────────────────────────

def require_tier(minimum: OrgTier):
    """
    Dependency factory — raises 403 if the org's tier is below `minimum`.

    Example::

        @router.get("/analytics/overview")
        async def analytics(org = Depends(require_tier(OrgTier.enterprise))):
            ...
    """
    async def _dep(org: Organization = Depends(get_current_org)) -> Organization:
        if TIER_ORDER.get(org.tier, 0) < TIER_ORDER.get(minimum, 0):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This feature requires the {minimum.value.title()} plan or higher. "
                    f"Your current plan is {org.tier.value.title()}."
                ),
            )
        return org

    return _dep


# ─── Subscription check ───────────────────────────────────────────────────────

def require_active_subscription(allow_starter_without_stripe: bool = True):
    """
    Raises 402 if the org has a subscription that is past_due, canceled, or unpaid.
    Starter orgs without a Stripe subscription are let through by default
    (free trial / dev use).
    """
    async def _dep(org: Organization = Depends(get_current_org)) -> Organization:
        if org.stripe_subscription_id is None:
            if not allow_starter_without_stripe:
                raise HTTPException(
                    status.HTTP_402_PAYMENT_REQUIRED,
                    detail="No active subscription. Please subscribe to continue.",
                )
            return org  # no stripe sub = allowed as free/dev

        bad_statuses = {"canceled", "unpaid"}
        if org.stripe_subscription_status in bad_statuses:
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    f"Your subscription is {org.stripe_subscription_status}. "
                    "Please update your payment method to continue."
                ),
            )
        return org

    return _dep


# ─── Scan limit ───────────────────────────────────────────────────────────────

async def check_scan_limit(org: Organization) -> None:
    """
    Raises 429 if the org has exhausted its monthly scan quota.
    Call this before queuing a new scan.
    """
    limit = org.scan_limit
    if limit == -1:
        return  # unlimited

    if org.scan_count_current_period >= limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Monthly scan limit reached ({org.scan_count_current_period}/{limit}). "
                "Upgrade your plan or wait until the next billing period."
            ),
        )


# ─── Feature flag ─────────────────────────────────────────────────────────────

FEATURE_TIERS: dict[str, OrgTier] = {
    "fraud_layer":   OrgTier.pro,
    "pdf_reports":   OrgTier.pro,
    "api_access":    OrgTier.pro,
    "batch_api":     OrgTier.enterprise,
    "analytics":     OrgTier.enterprise,
    "white_label":   OrgTier.enterprise,
}


def org_has_feature(org: Organization, feature: str) -> bool:
    required = FEATURE_TIERS.get(feature, OrgTier.starter)
    return TIER_ORDER.get(org.tier, 0) >= TIER_ORDER.get(required, 0)
