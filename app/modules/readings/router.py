import uuid

from app.models import User, UserRole
from app.modules.auth.deps import CurrentUser
from app.modules.readings import schemas
from app.modules.readings.deps import ReadingsServiceDep
from fastapi import APIRouter, Query

router = APIRouter(prefix="/sites", tags=["readings"])


def _scope(current_user: User) -> uuid.UUID | None:
    return None if current_user.role == UserRole.SUPER_ADMIN else current_user.company_id


@router.get("", response_model=list[schemas.SiteResponse])
async def list_sites(current_user: CurrentUser, service: ReadingsServiceDep):
    return await service.list_sites(_scope(current_user))


@router.get("/{site_id}/readings", response_model=list[schemas.SensorReadingResponse])
async def list_readings(
    site_id: uuid.UUID,
    current_user: CurrentUser,
    service: ReadingsServiceDep,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    return await service.list_readings(site_id, _scope(current_user), limit=limit, offset=offset)
