"""
Batch scan job — tracks async progress of multi-release scan submissions.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Integer, ForeignKey, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
import enum

from database import Base


class BatchJobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    complete = "complete"
    failed = "failed"


class BatchJob(Base):
    __tablename__ = "batch_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[BatchJobStatus] = mapped_column(
        SAEnum(BatchJobStatus, name="batch_job_status"),
        default=BatchJobStatus.pending,
        nullable=False,
    )
    # Counts for progress reporting
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Snapshot of which releases / scans belong to this batch
    release_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    scan_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Optional caller-supplied label for the batch
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<BatchJob id={self.id} status={self.status} "
            f"{self.completed}/{self.total}>"
        )
