import enum
import uuid
from datetime import datetime

from app.models.base import Base, TimestampMixin
from app.models.enums import ChecklistItemStatus, VisitStatus
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func


def _str_enum(enum_cls: type[enum.Enum]) -> Enum:
    # Stored as VARCHAR rather than a Postgres enum type, so adding a status
    # later doesn't need an ALTER TYPE migration.
    return Enum(
        enum_cls,
        native_enum=False,
        length=20,
        values_callable=lambda e: [m.value for m in e],
    )


class SiteVisit(TimestampMixin, Base):
    """An installer's on-site survey of a Site, with its checklist (FR6)."""

    __tablename__: str = "site_visits"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    visited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    visited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[VisitStatus] = mapped_column(
        _str_enum(VisitStatus), default=VisitStatus.IN_PROGRESS, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list[ChecklistItem]] = relationship(
        back_populates="visit",
        cascade="all, delete-orphan",
        order_by="ChecklistItem.position",
        lazy="selectin",
    )


class ChecklistItem(Base):
    __tablename__: str = "checklist_items"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    visit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("site_visits.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[ChecklistItemStatus] = mapped_column(
        _str_enum(ChecklistItemStatus), default=ChecklistItemStatus.PENDING, nullable=False
    )
    # Free-text answer for items that record a measurement or choice
    # ("45 m2", "three phase", "metal deck"); status alone covers yes/no checks.
    value: Mapped[str | None] = mapped_column(String(300), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    visit: Mapped[SiteVisit] = relationship(back_populates="items")
