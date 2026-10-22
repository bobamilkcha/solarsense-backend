import uuid
from datetime import date

from app.models.base import Base, TimestampMixin
from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class TNBBill(TimestampMixin, Base):
    """A parsed TNB electricity bill for a site.

    Fields extracted by the (best-effort) parser are nullable — a bill whose
    layout doesn't match what the parser expects still gets stored with
    whatever it could extract, rather than being rejected outright.
    """

    __tablename__: str = "tnb_bills"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    object_key: Mapped[str] = mapped_column(String, nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    billing_period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    billing_period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    kwh_used: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    tariff_category: Mapped[str | None] = mapped_column(String, nullable=True)
    # Total payable, including any previous balance ("Jumlah Bil Anda").
    amount_due: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    # This period's charges only ("Caj Semasa") — use this for cost/savings maths.
    current_charges: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
