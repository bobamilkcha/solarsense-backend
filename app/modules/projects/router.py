import uuid

from app.models import UserRole
from app.modules.auth.deps import CurrentUser, require_roles
from app.modules.projects import schemas
from app.modules.projects.deps import ProjectsServiceDep
from app.modules.readings.schemas import SiteResponse
from fastapi import APIRouter, status

router = APIRouter(prefix="/projects", tags=["projects"])


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
    company_id = None if current_user.role == UserRole.SUPER_ADMIN else current_user.company_id
    return await service.list_projects(company_id)


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
    company_id = None if current_user.role == UserRole.SUPER_ADMIN else current_user.company_id
    return await service.create_site(project_id, company_id, data)
