import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Integer, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
import enum

from database import Base


class OrgTier(str, enum.Enum):
    starter = "starter"
    pro = "pro"
    enterprise = "enterprise"


# Tier ordering — used for feature gate comparisons
TIER_ORDER: dict["OrgTier", int] = {
    OrgTier.starter: 0,
    OrgTier.pro: 1,
    OrgTier.enterprise: 2,
}

# Layers each tier is permitted to run
TIER_LAYERS: dict["OrgTier", list[str]] = {
    OrgTier.starter:    ["ddex", "metadata"],
    OrgTier.pro:        ["ddex", "metadata", "fraud", "audio", "artwork", "enrichment"],
    OrgTier.enterprise: ["ddex", "metadata", "fraud", "audio", "artwork", "enrichment"],
}

# Monthly scan limits per tier (-1 = unlimited)
TIER_SCAN_LIMIT: dict["OrgTier", int] = {
    OrgTier.starter:    50,
    OrgTier.pro:        500,
    OrgTier.enterprise: -1,
}


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    clerk_org_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    tier: Mapped[OrgTier] = mapped_column(
        SAEnum(OrgTier, name="org_tier"), default=OrgTier.starter, nullable=False
    )
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # ── Stripe billing fields ─────────────────────────────────────────────────
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String, nullable=True, unique=True, index=True
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String, nullable=True, unique=True, index=True
    )
    stripe_subscription_status: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # active | trialing | past_due | canceled | unpaid
    stripe_price_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stripe_subscription_item_id: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # for usage-record reporting on metered items
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Local scan counter — reset at the start of each billing period
    scan_count_current_period: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @property
    def scan_limit(self) -> int:
        return TIER_SCAN_LIMIT.get(self.tier, 50)

    @property
    def allowed_layers(self) -> list[str]:
        return TIER_LAYERS.get(self.tier, ["ddex", "metadata"])

    @property
    def subscription_is_active(self) -> bool:
        return self.stripe_subscription_status in {"active", "trialing"}

    def __repr__(self) -> str:
        return f"<Organization id={self.id} name={self.name!r} tier={self.tier}>"
