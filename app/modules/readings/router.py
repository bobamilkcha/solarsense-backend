import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from app.modules.auth.deps import CurrentUser, company_scope
from app.modules.readings import schemas
from app.modules.readings.deps import ReadingsServiceDep
from app.modules.readings.exceptions import ExportTooLargeError
from app.modules.readings.export import XLSX_MAX_ROWS, readings_to_csv, readings_to_xlsx
from fastapi import APIRouter, Query
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

router = APIRouter(prefix="/sites", tags=["readings"])


@router.get("", response_model=list[schemas.SiteResponse])
async def list_sites(current_user: CurrentUser, service: ReadingsServiceDep):
    return await service.list_sites(company_scope(current_user))


@router.get("/{site_id}/readings", response_model=list[schemas.SensorReadingResponse])
async def list_readings(
    site_id: uuid.UUID,
    current_user: CurrentUser,
    service: ReadingsServiceDep,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    return await service.list_readings(
        site_id, company_scope(current_user), limit=limit, offset=offset
    )


@router.get(
    "/{site_id}/readings/export",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}, XLSX_MEDIA_TYPE: {}}}},
)
async def export_readings(
    site_id: uuid.UUID,
    current_user: CurrentUser,
    service: ReadingsServiceDep,
    format: Literal["csv", "xlsx"] = "csv",
    start: Annotated[datetime | None, Query(description="Inclusive, ISO 8601")] = None,
    end: Annotated[datetime | None, Query(description="Exclusive, ISO 8601")] = None,
):
    site, readings = await service.export_readings(
        site_id, company_scope(current_user), start=start, end=end
    )

    if format == "xlsx":
        if len(readings) > XLSX_MAX_ROWS:
            raise ExportTooLargeError
        data = await run_in_threadpool(readings_to_xlsx, readings)
        media_type = XLSX_MEDIA_TYPE
    else:
        data = await run_in_threadpool(readings_to_csv, readings)
        media_type = "text/csv; charset=utf-8"

    filename = f"readings-{site.device_id}-{datetime.now(UTC):%Y%m%d}.{format}"
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
