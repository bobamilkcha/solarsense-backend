import uuid

from app.modules.auth.deps import CurrentUser, company_scope
from app.modules.benchmark.deps import BenchmarkServiceDep
from app.modules.benchmark.schemas import BenchmarkResponse
from fastapi import APIRouter, Query

router = APIRouter(prefix="/sites", tags=["benchmark"])


@router.get("/{site_id}/benchmark", response_model=BenchmarkResponse)
async def get_benchmark(
    site_id: uuid.UUID,
    current_user: CurrentUser,
    service: BenchmarkServiceDep,
    month: int | None = Query(default=None, ge=1, le=12),
):
    return await service.compare(site_id, company_scope(current_user), month=month)
