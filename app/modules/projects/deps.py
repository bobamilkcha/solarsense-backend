from typing import Annotated

from app.core.deps import DBSession
from app.modules.projects.service import ProjectsService
from fastapi import Depends


def get_projects_service(db: DBSession) -> ProjectsService:
    return ProjectsService(db)


ProjectsServiceDep = Annotated[ProjectsService, Depends(get_projects_service)]
