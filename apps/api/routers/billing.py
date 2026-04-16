"""
Billing management endpoints — Stripe integration.

All routes use Clerk JWT auth (get_current_org).

GET  /billing/plans          — available plans with pricing
GET  /billing/subscription   — current plan, usage, period
POST /billing/checkout       — create Stripe Checkout Session (returns URL)
POST /billing/portal         — create Stripe Customer Portal Session (returns URL)
GET  /billing/invoices       — invoice history
POST /billing/api-keys       — create an API key (Clerk JWT auth, for onboarding bootstrap)
GET  /billing/api-keys       — list API keys for the org
DELETE /billing/api-keys/{key_id} — revoke an API key
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies.auth import get_current_org, get_current_user_id
from models.api_key import APIKey
from models.organization import Organization, OrgTier, TIER_SCAN_LIMIT
from services.billing import (
    create_checkout_session,
    create_portal_session,
    list_invoices,
)
from config import settings

router = APIRouter(prefix="/billing")


# ─── Schemas ──────────────────────────────────────────────────────────────────

class PlanInfo(BaseModel):
    id: str                  # "starter" | "pro" | "enterprise"
    name: str
    price_monthly_usd: int   # 0 for custom Enterprise
    scan_limit: int          # -1 for unlimited
    price_id: str | None     # Stripe price ID (None for Enterprise / no config)
    features: list[str]


class SubscriptionOut(BaseModel):
    tier: str
    plan_name: str
    status: str | None
    scan_count: int
    scan_limit: int
    period_start: datetime | None
    period_end:   datetime | None
    is_active: bool


class CheckoutIn(BaseModel):
    price_id: str


class SessionURLOut(BaseModel):
    url: str


class InvoiceOut(BaseModel):
    id: str
    number: str | None
    status: str
    amount_paid_usd: float
    currency: str
    period_start: datetime | None
    period_end:   datetime | None
    invoice_pdf: str | None
    hosted_invoice_url: str | None


# ─── Helpers ──────────────────────────────────────────────────────────────────

_PLAN_FEATURES = {
    OrgTier.starter: [
        "DDEX & metadata validation",
        "Up to 50 releases/month",
        "Basic QA report",
        "Email support",
    ],
    OrgTier.pro: [
        "All 6 QA layers (DDEX, metadata, fraud, audio, artwork, enrichment)",
        "Up to 500 releases/month",
        "PDF QA reports",
        "Public REST API access",
        "Priority support",
    ],
    OrgTier.enterprise: [
        "Unlimited releases",
        "Batch API (up to 100 releases/call)",
        "Analytics corpus dashboard",
        "White-label reports",
        "Dedicated SLA + onboarding",
    ],
}

def _plan_info(tier: OrgTier) -> PlanInfo:
    prices = {
        OrgTier.starter:    (500,   settings.stripe_starter_price_id),
        OrgTier.pro:        (2000,  settings.stripe_pro_price_id),
        OrgTier.enterprise: (8000,  settings.stripe_enterprise_price_id),
    }
    names = {
        OrgTier.starter:    "Starter",
        OrgTier.pro:        "Professional",
        OrgTier.enterprise: "Enterprise",
    }
    usd, price_id = prices[tier]
    return PlanInfo(
        id=tier.value,
        name=names[tier],
        price_monthly_usd=usd,
        scan_limit=TIER_SCAN_LIMIT[tier],
        price_id=price_id or None,
        features=_PLAN_FEATURES[tier],
    )


def _ts_to_dt(ts: int | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("/plans", response_model=list[PlanInfo], summary="Available plans")
async def get_plans(org: Organization = Depends(get_current_org)) -> list[PlanInfo]:
    """Return all available pricing plans with features and Stripe price IDs."""
    return [_plan_info(t) for t in OrgTier]


@router.get(
    "/subscription",
    response_model=SubscriptionOut,
    summary="Current subscription and usage",
)
async def get_subscription(
    org: Organization = Depends(get_current_org),
) -> SubscriptionOut:
    """Return the org's current plan, scan usage, and billing period."""
    name_map = {OrgTier.starter: "Starter", OrgTier.pro: "Professional", OrgTier.enterprise: "Enterprise"}
    return SubscriptionOut(
        tier=org.tier.value,
        plan_name=name_map.get(org.tier, org.tier.value),
        status=org.stripe_subscription_status,
        scan_count=org.scan_count_current_period,
        scan_limit=org.scan_limit,
        period_start=org.current_period_start,
        period_end=org.current_period_end,
        is_active=org.subscription_is_active or org.stripe_subscription_id is None,
    )


@router.post(
    "/checkout",
    response_model=SessionURLOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create Stripe Checkout Session",
    description=(
        "Create a Stripe Checkout Session for the given price ID. "
        "Redirect the user to the returned `url` to complete payment. "
        "On success, Stripe will POST a `checkout.session.completed` webhook."
    ),
)
async def checkout(
    payload: CheckoutIn,
    org: Organization = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> SessionURLOut:
    if not settings.stripe_secret_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing is not yet configured. Contact sales@songgate.io to upgrade your plan.",
        )

    allowed_price_ids = {
        settings.stripe_starter_price_id,
        settings.stripe_pro_price_id,
        settings.stripe_enterprise_price_id,
    } - {""}

    if payload.price_id not in allowed_price_ids:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Invalid price ID.",
        )

    url = await create_checkout_session(org, payload.price_id)
    await db.commit()  # persist stripe_customer_id set by get_or_create_customer
    return SessionURLOut(url=url)


@router.post(
    "/portal",
    response_model=SessionURLOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create Stripe Customer Portal Session",
    description=(
        "Create a Stripe Billing Portal Session. "
        "Redirect the user to the returned `url` to manage their subscription, "
        "update payment methods, or download invoices."
    ),
)
async def portal(
    org: Organization = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> SessionURLOut:
    if not settings.stripe_secret_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing is not yet configured. Contact sales@songgate.io to upgrade your plan.",
        )
    if not org.stripe_customer_id and not org.stripe_subscription_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="No billing account found. Subscribe to a plan first.",
        )
    url = await create_portal_session(org)
    await db.commit()
    return SessionURLOut(url=url)


@router.get(
    "/invoices",
    response_model=list[InvoiceOut],
    summary="Invoice history",
)
async def invoices(
    org: Organization = Depends(get_current_org),
) -> list[InvoiceOut]:
    """Return the last 24 invoices for the org's Stripe customer."""
    raw = await list_invoices(org)
    return [
        InvoiceOut(
            id=inv["id"],
            number=inv.get("number"),
            status=inv["status"],
            amount_paid_usd=inv["amount_paid"] / 100,
            currency=inv["currency"].upper(),
            period_start=_ts_to_dt(inv.get("period_start")),
            period_end=_ts_to_dt(inv.get("period_end")),
            invoice_pdf=inv.get("invoice_pdf"),
            hosted_invoice_url=inv.get("hosted_invoice_url"),
        )
        for inv in raw
    ]


# ─── API Key management (Clerk JWT auth) ──────────────────────────────────────
# These routes let dashboard users create/list/revoke API keys without needing
# a pre-existing API key — solving the onboarding bootstrapping problem.

class APIKeyCreateIn(BaseModel):
    name: str


class APIKeyOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked: bool


class APIKeyCreatedOut(APIKeyOut):
    key: str  # Plaintext — shown once only


def _generate_api_key() -> tuple[str, str, str]:
    """Return (plaintext_key, key_prefix, key_hash)."""
    raw = secrets.token_hex(40)
    plaintext = f"ropqa_sk_{raw}"
    prefix = plaintext[:16]
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    return plaintext, prefix, key_hash


@router.post(
    "/api-keys",
    response_model=APIKeyCreatedOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create API key",
    description=(
        "Create a new API key for this organization using Clerk JWT auth. "
        "The plaintext key is returned **once** and cannot be retrieved again. "
        "Store it securely. Professional and Enterprise plans only."
    ),
)
async def create_api_key(
    payload: APIKeyCreateIn,
    org: Organization = Depends(get_current_org),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> APIKeyCreatedOut:
    if org.tier == OrgTier.starter:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="API key creation requires Professional or Enterprise plan.",
        )

    plaintext, prefix, key_hash = _generate_api_key()
    key = APIKey(
        org_id=org.id,
        name=payload.name,
        key_prefix=prefix,
        key_hash=key_hash,
        created_by=user_id,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)

    return APIKeyCreatedOut(
        id=str(key.id),
        name=key.name,
        key_prefix=key.key_prefix,
        key=plaintext,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        revoked=key.revoked,
    )


@router.get(
    "/api-keys",
    response_model=list[APIKeyOut],
    summary="List API keys",
)
async def list_api_keys(
    org: Organization = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> list[APIKeyOut]:
    """List all non-revoked API keys for this organization."""
    result = await db.execute(
        select(APIKey)
        .where(APIKey.org_id == org.id, APIKey.revoked.is_(False))
        .order_by(APIKey.created_at.desc())
    )
    keys = result.scalars().all()
    return [
        APIKeyOut(
            id=str(k.id),
            name=k.name,
            key_prefix=k.key_prefix,
            created_at=k.created_at,
            last_used_at=k.last_used_at,
            revoked=k.revoked,
        )
        for k in keys
    ]


@router.delete(
    "/api-keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Revoke API key",
)
async def revoke_api_key(
    key_id: str,
    org: Organization = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete an API key. Revoked keys are rejected immediately."""
    result = await db.execute(
        select(APIKey).where(APIKey.id == key_id, APIKey.org_id == org.id)
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="API key not found.")
    key.revoked = True
    key.revoked_at = datetime.now(timezone.utc)
    await db.commit()


# ─── Notification settings ────────────────────────────────────────────────────

class NotifEmailIn(BaseModel):
    email: str


@router.post(
    "/notification-email",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Set notification email",
    description="Save an email address to receive scan-complete and scan-failed notifications.",
)
async def set_notification_email(
    payload: NotifEmailIn,
    org: Organization = Depends(get_current_org),
    db: AsyncSession = Depends(get_db),
) -> None:
    settings_copy = dict(org.settings or {})
    settings_copy["notification_email"] = payload.email
    org.settings = settings_copy
    await db.commit()
