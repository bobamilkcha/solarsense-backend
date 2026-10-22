from typing import Annotated

from app.core.deps import DBSession
from app.modules.reports.service import ReportsService
from fastapi import Depends


def get_reports_service(db: DBSession) -> ReportsService:
    return ReportsService(db)


ReportsServiceDep = Annotated[ReportsService, Depends(get_reports_service)]
