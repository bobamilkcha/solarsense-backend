from typing import Annotated

from app.core.deps import DBSession
from app.modules.visits.service import VisitsService
from fastapi import Depends


def get_visits_service(db: DBSession) -> VisitsService:
    return VisitsService(db)


VisitsServiceDep = Annotated[VisitsService, Depends(get_visits_service)]
