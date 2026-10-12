import uuid
from collections.abc import Sequence

from app.models import Project, Site
from app.modules.projects.exceptions import DeviceIdAlreadyExistsError, ProjectNotFoundError
from app.modules.projects.schemas import ProjectCreateRequest, SiteCreateRequest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class ProjectsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_project(self, company_id: uuid.UUID, data: ProjectCreateRequest) -> Project:
        project = Project(company_id=company_id, name=data.name, description=data.description)
        self.db.add(project)
        await self.db.commit()
        await self.db.refresh(project)
        return project

    async def list_projects(self, company_id: uuid.UUID | None) -> Sequence[Project]:
        """`company_id=None` lists across every company (super_admin only)."""
        stmt = select(Project).order_by(Project.name)
        if company_id is not None:
            stmt = stmt.where(Project.company_id == company_id)
        result = await self.db.scalars(stmt)
        return result.all()

    async def create_site(
        self, project_id: uuid.UUID, company_id: uuid.UUID | None, data: SiteCreateRequest
    ) -> Site:
        """`company_id=None` skips the ownership check (super_admin only)."""
        project = await self.db.get(Project, project_id)
        if project is None or (company_id is not None and project.company_id != company_id):
            raise ProjectNotFoundError

        existing = await self.db.scalar(select(Site).where(Site.device_id == data.device_id))
        if existing is not None:
            raise DeviceIdAlreadyExistsError

        site = Site(
            project_id=project_id,
            name=data.name,
            device_id=data.device_id,
            location_lat=data.location_lat,
            location_lng=data.location_lng,
        )
        self.db.add(site)
        await self.db.commit()
        await self.db.refresh(site)
        return site
