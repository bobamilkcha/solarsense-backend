import uuid
from datetime import UTC, datetime
from typing import Annotated

from app.modules.auth.deps import CurrentUser, company_scope
from app.modules.reports.deps import ReportsServiceDep
from app.modules.reports.excel import render_feasibility_xlsx
from app.modules.reports.schemas import AssumptionsParams, FeasibilityReport
from fastapi import APIRouter, Query
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/sites", tags=["reports"])


@router.get("/{site_id}/feasibility", response_model=FeasibilityReport)
async def get_feasibility(
    site_id: uuid.UUID,
    current_user: CurrentUser,
    service: ReportsServiceDep,
    params: Annotated[AssumptionsParams, Query()],
):
    return await service.feasibility(site_id, company_scope(current_user), params)


XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get(
    "/{site_id}/feasibility/xlsx",
    response_class=Response,
    responses={200: {"content": {XLSX_MEDIA_TYPE: {}}}},
)
async def get_feasibility_xlsx(
    site_id: uuid.UUID,
    current_user: CurrentUser,
    service: ReportsServiceDep,
    params: Annotated[AssumptionsParams, Query()],
):
    report = await service.feasibility(site_id, company_scope(current_user), params)
    now = datetime.now(UTC)
    # openpyxl is synchronous; keep it off the event loop.
    data = await run_in_threadpool(render_feasibility_xlsx, report, now)
    filename = f"feasibility-{site_id}-{now:%Y%m%d}.xlsx"
    return Response(
        content=data,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
