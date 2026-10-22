import uuid

from app.modules.auth.deps import CurrentUser, company_scope
from app.modules.visits import schemas
from app.modules.visits.deps import VisitsServiceDep
from app.modules.visits.service import to_response, to_summary
from fastapi import APIRouter, status

# Any company member can run a visit — installers are the ones on site.
sites_router = APIRouter(prefix="/sites", tags=["visits"])
router = APIRouter(prefix="/visits", tags=["visits"])


@sites_router.post(
    "/{site_id}/visits",
    response_model=schemas.VisitResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_visit(
    site_id: uuid.UUID,
    data: schemas.VisitCreateRequest,
    current_user: CurrentUser,
    service: VisitsServiceDep,
):
    visit = await service.create_visit(site_id, company_scope(current_user), current_user, data)
    return to_response(visit)


@sites_router.get("/{site_id}/visits", response_model=list[schemas.VisitSummaryResponse])
async def list_visits(site_id: uuid.UUID, current_user: CurrentUser, service: VisitsServiceDep):
    visits = await service.list_visits(site_id, company_scope(current_user))
    return [to_summary(v) for v in visits]


@router.get("/{visit_id}", response_model=schemas.VisitResponse)
async def get_visit(visit_id: uuid.UUID, current_user: CurrentUser, service: VisitsServiceDep):
    return to_response(await service.get_visit(visit_id, company_scope(current_user)))


@router.patch("/{visit_id}", response_model=schemas.VisitResponse)
async def update_visit(
    visit_id: uuid.UUID,
    data: schemas.VisitUpdateRequest,
    current_user: CurrentUser,
    service: VisitsServiceDep,
):
    visit = await service.update_visit(visit_id, company_scope(current_user), data)
    return to_response(visit)


@router.delete("/{visit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_visit(visit_id: uuid.UUID, current_user: CurrentUser, service: VisitsServiceDep):
    await service.delete_visit(visit_id, company_scope(current_user))


@router.post(
    "/{visit_id}/items",
    response_model=schemas.ChecklistItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_item(
    visit_id: uuid.UUID,
    data: schemas.ChecklistItemCreateRequest,
    current_user: CurrentUser,
    service: VisitsServiceDep,
):
    return await service.add_item(visit_id, company_scope(current_user), data)


@router.patch("/{visit_id}/items/{item_id}", response_model=schemas.ChecklistItemResponse)
async def update_item(
    visit_id: uuid.UUID,
    item_id: uuid.UUID,
    data: schemas.ChecklistItemUpdateRequest,
    current_user: CurrentUser,
    service: VisitsServiceDep,
):
    return await service.update_item(visit_id, item_id, company_scope(current_user), data)


@router.delete("/{visit_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    visit_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: CurrentUser,
    service: VisitsServiceDep,
):
    await service.delete_item(visit_id, item_id, company_scope(current_user))
