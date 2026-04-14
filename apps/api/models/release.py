import uuid
from datetime import date, datetime, timezone

from sqlalchemy import String, DateTime, Date, Enum as SAEnum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
import enum

from database import Base


class SubmissionFormat(str, enum.Enum):
    DDEX_ERN_43 = "DDEX_ERN_43"
    DDEX_ERN_42 = "DDEX_ERN_42"
    CSV = "CSV"
    JSON = "JSON"


class ReleaseStatus(str, enum.Enum):
    pending = "pending"
    ingesting = "ingesting"
    ready = "ready"
    scanning = "scanning"
    complete = "complete"
    failed = "failed"


class Release(Base):
    __tablename__ = "releases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    artist: Mapped[str] = mapped_column(String, nullable=False)
    upc: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    submission_format: Mapped[SubmissionFormat] = mapped_column(
        SAEnum(SubmissionFormat, name="submission_format"), nullable=False
    )
    raw_package_url: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    status: Mapped[ReleaseStatus] = mapped_column(
        SAEnum(ReleaseStatus, name="release_status"), default=ReleaseStatus.pending, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Release id={self.id} title={self.title!r} upc={self.upc}>"
