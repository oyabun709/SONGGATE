"""
API key model for the public /api/v1/ surface.

Keys are stored as `ropqa_sk_<32 hex chars>`.  Only the SHA-256 hash is
persisted — the plaintext is shown once on creation and never again.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class APIKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Human-readable label supplied by the caller
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # First 16 chars of the plaintext key — safe to display, used for identification
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # SHA-256 hex digest of the full plaintext key
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # Optional: who created this key (Clerk user_id, best-effort)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<APIKey id={self.id} prefix={self.key_prefix!r} revoked={self.revoked}>"
