import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Boolean, Enum as SAEnum, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column
import enum

from database import Base


class ResultStatus(str, enum.Enum):
    fail = "fail"
    warn = "warn"
    pass_ = "pass"


class ScanResult(Base):
    __tablename__ = "scan_results"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    track_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tracks.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Rule linkage
    layer: Mapped[str] = mapped_column(String, nullable=False)
    rule_id: Mapped[str] = mapped_column(
        String, ForeignKey("rules.id", ondelete="SET NULL"), nullable=False
    )
    severity: Mapped[str] = mapped_column(String, nullable=False)  # critical/warning/info

    # Evaluation outcome
    status: Mapped[ResultStatus] = mapped_column(
        SAEnum(ResultStatus, name="result_status"), nullable=False
    )
    message: Mapped[str] = mapped_column(String, nullable=False)
    field_path: Mapped[str | None] = mapped_column(String, nullable=True)
    actual_value: Mapped[str | None] = mapped_column(String, nullable=True)
    expected_value: Mapped[str | None] = mapped_column(String, nullable=True)
    fix_hint: Mapped[str | None] = mapped_column(String, nullable=True)
    dsp_targets: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list, server_default=text("'{}'")
    )

    # Resolution
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolution: Mapped[str | None] = mapped_column(String, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String, nullable=True)

    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    __table_args__ = (
        Index("ix_scan_results_rule_id", "rule_id"),
        Index("ix_scan_results_layer", "layer"),
        Index("ix_scan_results_severity", "severity"),
        Index("ix_scan_results_resolved", "resolved"),
        Index(
            "ix_scan_results_dsp_targets_gin",
            "dsp_targets",
            postgresql_using="gin",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ScanResult id={self.id} rule_id={self.rule_id!r} "
            f"status={self.status} severity={self.severity}>"
        )
