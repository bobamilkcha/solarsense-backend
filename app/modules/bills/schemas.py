import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class TNBBillResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    site_id: uuid.UUID
    filename: str
    billing_period_start: date | None
    billing_period_end: date | None
    kwh_used: float | None
    tariff_category: str | None
    amount_due: float | None
    current_charges: float | None
    created_at: datetime
