import uuid
from collections.abc import Sequence

from app.core.logging.service import get_log_service
from app.core.storage.object_storage import delete_prefix
from app.models import Project, Site
from app.modules.bills.service import BILLS_BUCKET
from app.modules.projects.exceptions import DeviceIdAlreadyExistsError, ProjectNotFoundError
from app.modules.projects.schemas import (
    ProjectCreateRequest,
    ProjectUpdateRequest,
    SiteCreateRequest,
    SiteUpdateRequest,
)
from app.modules.readings.exceptions import SiteNotFoundError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_log = get_log_service()


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

    async def update_project(
        self, project_id: uuid.UUID, company_id: uuid.UUID | None, data: ProjectUpdateRequest
    ) -> Project:
        project = await self._get_project(project_id, company_id)
        for field, value in data.changes().items():
            setattr(project, field, value)
        await self.db.commit()
        await self.db.refresh(project)
        return project

    async def delete_project(self, project_id: uuid.UUID, company_id: uuid.UUID | None) -> None:
        """Deletes the project and all its sites (readings, bills, visits cascade)."""
        project = await self._get_project(project_id, company_id)
        site_ids = list(await self.db.scalars(select(Site.id).where(Site.project_id == project.id)))
        await self.db.delete(project)
        await self.db.commit()
        for site_id in site_ids:
            await self._delete_site_files(site_id)

    async def create_site(
        self, project_id: uuid.UUID, company_id: uuid.UUID | None, data: SiteCreateRequest
    ) -> Site:
        """`company_id=None` skips the ownership check (super_admin only)."""
        await self._get_project(project_id, company_id)

        if data.device_id is not None:
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

    async def update_site(
        self, site_id: uuid.UUID, company_id: uuid.UUID | None, data: SiteUpdateRequest
    ) -> Site:
        site = await self._get_site(site_id, company_id)
        for field, value in data.changes().items():
            setattr(site, field, value)
        await self.db.commit()
        await self.db.refresh(site)
        return site

    async def delete_site(self, site_id: uuid.UUID, company_id: uuid.UUID | None) -> None:
        """Deletes the site; its readings, bills and visits cascade. Its device
        (if any) becomes unpaired and can be paired to another site."""
        site = await self._get_site(site_id, company_id)
        await self.db.delete(site)
        await self.db.commit()
        await self._delete_site_files(site_id)

    async def _get_project(self, project_id: uuid.UUID, company_id: uuid.UUID | None) -> Project:
        """`company_id=None` skips the ownership check (super_admin only). Another
        company's project is a 404, not a 403, so its existence isn't leaked."""
        project = await self.db.get(Project, project_id)
        if project is None or (company_id is not None and project.company_id != company_id):
            raise ProjectNotFoundError
        return project

    async def _get_site(self, site_id: uuid.UUID, company_id: uuid.UUID | None) -> Site:
        site = await self.db.get(Site, site_id)
        if site is None:
            raise SiteNotFoundError
        if company_id is not None:
            project = await self.db.get(Project, site.project_id)
            if project is None or project.company_id != company_id:
                raise SiteNotFoundError
        return site

    async def _delete_site_files(self, site_id: uuid.UUID) -> None:
        # Bill PDFs are stored under "<site_id>/". The DB rows are already gone,
        # so a failure here only leaves orphaned files; log it, don't fail the request.
        try:
            await delete_prefix(BILLS_BUCKET, str(site_id))
        except OSError as exc:
            _log.warning("site_files_delete_failed", site_id=str(site_id), error=str(exc))
