import uuid

from app.models import UserRole
from app.modules.auth.deps import CurrentUser, company_scope, require_roles
from app.modules.projects import schemas
from app.modules.projects.deps import ProjectsServiceDep
from app.modules.readings.schemas import SiteResponse
from fastapi import APIRouter, status

router = APIRouter(prefix="/projects", tags=["projects"])
# Edit/delete of sites lives here too, since this module creates them.
sites_router = APIRouter(prefix="/sites", tags=["projects"])

admin_only = [require_roles(UserRole.COMPANY_ADMIN)]


@router.post(
    "",
    response_model=schemas.ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_roles(UserRole.COMPANY_ADMIN)],
)
async def create_project(
    data: schemas.ProjectCreateRequest, current_user: CurrentUser, service: ProjectsServiceDep
):
    return await service.create_project(current_user.company_id, data)


@router.get("", response_model=list[schemas.ProjectResponse])
async def list_projects(current_user: CurrentUser, service: ProjectsServiceDep):
    return await service.list_projects(company_scope(current_user))


@router.post(
    "/{project_id}/sites",
    response_model=SiteResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_roles(UserRole.COMPANY_ADMIN)],
)
async def create_site(
    project_id: uuid.UUID,
    data: schemas.SiteCreateRequest,
    current_user: CurrentUser,
    service: ProjectsServiceDep,
):
    return await service.create_site(project_id, company_scope(current_user), data)


@router.patch("/{project_id}", response_model=schemas.ProjectResponse, dependencies=admin_only)
async def update_project(
    project_id: uuid.UUID,
    data: schemas.ProjectUpdateRequest,
    current_user: CurrentUser,
    service: ProjectsServiceDep,
):
    """Change the name and/or description. Only the fields sent are changed."""
    return await service.update_project(project_id, company_scope(current_user), data)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=admin_only)
async def delete_project(
    project_id: uuid.UUID, current_user: CurrentUser, service: ProjectsServiceDep
) -> None:
    """Delete the project and all its sites, with their readings, bills and visits."""
    await service.delete_project(project_id, company_scope(current_user))


@sites_router.patch("/{site_id}", response_model=SiteResponse, dependencies=admin_only)
async def update_site(
    site_id: uuid.UUID,
    data: schemas.SiteUpdateRequest,
    current_user: CurrentUser,
    service: ProjectsServiceDep,
):
    """Change the name and/or location. Only the fields sent are changed. To change
    the device, use PUT/DELETE /sites/{site_id}/device."""
    return await service.update_site(site_id, company_scope(current_user), data)


@sites_router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=admin_only)
async def delete_site(
    site_id: uuid.UUID, current_user: CurrentUser, service: ProjectsServiceDep
) -> None:
    """Delete the site with its readings, bills and visits. Its device becomes unpaired."""
    await service.delete_site(site_id, company_scope(current_user))
