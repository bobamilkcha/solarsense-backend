import uuid
from datetime import datetime

from app.models import ChecklistItemStatus, VisitStatus
from pydantic import BaseModel, ConfigDict, Field


class VisitCreateRequest(BaseModel):
    visited_at: datetime | None = Field(default=None, description="Defaults to now")
    notes: str | None = Field(default=None, max_length=10_000)
    use_default_checklist: bool = True


class VisitUpdateRequest(BaseModel):
    visited_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=10_000)
    # completed requires no pending items; in_progress reopens a completed visit
    status: VisitStatus | None = None


class ChecklistItemCreateRequest(BaseModel):
    category: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=300)


class ChecklistItemUpdateRequest(BaseModel):
    category: str | None = Field(default=None, min_length=1, max_length=100)
    label: str | None = Field(default=None, min_length=1, max_length=300)
    status: ChecklistItemStatus | None = None
    value: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=10_000)


class ChecklistItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    position: int
    category: str
    label: str
    status: ChecklistItemStatus
    value: str | None
    notes: str | None
    updated_at: datetime


class ChecklistProgress(BaseModel):
    total: int
    pending: int
    ok: int
    issue: int
    not_applicable: int


class VisitSummaryResponse(BaseModel):
    id: uuid.UUID
    site_id: uuid.UUID
    visited_by_id: uuid.UUID | None
    visited_at: datetime
    status: VisitStatus
    notes: str | None
    completed_at: datetime | None
    created_at: datetime
    progress: ChecklistProgress


class VisitResponse(VisitSummaryResponse):
    items: list[ChecklistItemResponse]
