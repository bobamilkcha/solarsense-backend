import uuid

from app.modules.auth.deps import CurrentUser
from app.modules.readings import schemas
from app.modules.readings.deps import ReadingsServiceDep
from fastapi import APIRouter, Query

router = APIRouter(prefix="/sites", tags=["readings"])


@router.get("", response_model=list[schemas.SiteResponse])
async def list_sites(current_user: CurrentUser, service: ReadingsServiceDep):
    return await service.list_sites()


@router.get("/{site_id}/readings", response_model=list[schemas.SensorReadingResponse])
async def list_readings(
    site_id: uuid.UUID,
    current_user: CurrentUser,
    service: ReadingsServiceDep,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    return await service.list_readings(site_id, limit=limit, offset=offset)
