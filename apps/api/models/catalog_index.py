import uuid
from datetime import datetime, date, timezone

from sqlalchemy import String, DateTime, Date, Boolean, Integer, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class CatalogIndex(Base):
    __tablename__ = "catalog_index"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ean: Mapped[str] = mapped_column(String(13), nullable=False)
    artist: Mapped[str | None] = mapped_column(String(500), nullable=True)
    artist_normalized: Mapped[str | None] = mapped_column(String(500), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    title_normalized: Mapped[str | None] = mapped_column(String(500), nullable=True)
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    imprint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    narm_config: Mapped[str | None] = mapped_column(String(10), nullable=True)
    isni: Mapped[str | None] = mapped_column(String(20), nullable=True)
    iswc: Mapped[str | None] = mapped_column(String(20), nullable=True)
    scan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scans.id", ondelete="SET NULL"),
        nullable=True,
    )
    # org_id has no FK — NULL is allowed for demo-mode scans
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    __table_args__ = (
        Index("ix_catalog_index_ean", "ean"),
        Index("ix_catalog_index_artist_normalized", "artist_normalized"),
        Index("ix_catalog_index_title_normalized", "title_normalized"),
        Index("ix_catalog_index_scan_id", "scan_id"),
        Index("ix_catalog_index_org_id", "org_id"),
    )

    def __repr__(self) -> str:
        return f"<CatalogIndex ean={self.ean!r} artist={self.artist!r}>"
