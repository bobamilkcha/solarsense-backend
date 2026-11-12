import uuid
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime


class SiteCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Optional: a site can be created first and paired later via PUT /sites/{id}/device.
    device_id: str | None = Field(default=None, min_length=1, max_length=200)
    location_lat: float = Field(ge=-90, le=90)
    location_lng: float = Field(ge=-180, le=180)


class _PartialUpdate(BaseModel):
    """PATCH body: only the fields sent are changed. Fields in `required_fields` may be
    left out but not sent as null."""

    required_fields: ClassVar[tuple[str, ...]] = ()

    @model_validator(mode="after")
    def _no_null_required(self):
        for field in self.required_fields:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class ProjectUpdateRequest(_PartialUpdate):
    required_fields = ("name",)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    # Send null to clear the description.
    description: str | None = None


class SiteUpdateRequest(_PartialUpdate):
    required_fields = ("name", "location_lat", "location_lng")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    location_lat: float | None = Field(default=None, ge=-90, le=90)
    location_lng: float | None = Field(default=None, ge=-180, le=180)
