import uuid
from typing import Annotated

from app.modules.auth.deps import CurrentUser, company_scope
from app.modules.reports.deps import ReportsServiceDep
from app.modules.reports.schemas import AssumptionsParams, FeasibilityReport
from fastapi import APIRouter, Query

router = APIRouter(prefix="/sites", tags=["reports"])


@router.get("/{site_id}/feasibility", response_model=FeasibilityReport)
async def get_feasibility(
    site_id: uuid.UUID,
    current_user: CurrentUser,
    service: ReportsServiceDep,
    params: Annotated[AssumptionsParams, Query()],
):
    return await service.feasibility(site_id, company_scope(current_user), params)
