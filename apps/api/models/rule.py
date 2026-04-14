from datetime import datetime, timezone

from sqlalchemy import String, Boolean, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Rule(Base):
    """
    Canonical rule registry.

    id follows the convention: <dsp_or_universal>.<layer>.<slug>
    e.g. 'spotify.metadata.contributor_publisher_required'
         'universal.audio.sample_rate_minimum'
    """

    __tablename__ = "rules"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    layer: Mapped[str] = mapped_column(String, nullable=False, index=True)
    dsp: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String, nullable=False)   # critical / warning / info
    category: Mapped[str] = mapped_column(String, nullable=False)   # e.g. contributors, audio, artwork
    fix_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    doc_url: Mapped[str | None] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[str] = mapped_column(String, default="1.0.0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Rule id={self.id!r} severity={self.severity} active={self.active}>"
