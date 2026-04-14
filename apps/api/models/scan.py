import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Enum as SAEnum, Integer, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
import enum

from database import Base


class ScanStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    complete = "complete"
    failed = "failed"


class ScanGrade(str, enum.Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("releases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ScanStatus] = mapped_column(
        SAEnum(ScanStatus, name="scan_status"), default=ScanStatus.queued, nullable=False
    )
    readiness_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0–100
    grade: Mapped[ScanGrade | None] = mapped_column(
        SAEnum(ScanGrade, name="scan_grade"), nullable=True
    )
    total_issues: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    critical_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warning_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    info_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    layers_run: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    report_url: Mapped[str | None] = mapped_column(String, nullable=True)
    report_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    def __repr__(self) -> str:
        return f"<Scan id={self.id} status={self.status} grade={self.grade}>"
