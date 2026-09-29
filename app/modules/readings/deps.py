from typing import Annotated

from app.core.deps import DBSession
from app.modules.readings.service import ReadingsService
from fastapi import Depends


def get_readings_service(db: DBSession) -> ReadingsService:
    return ReadingsService(db)


ReadingsServiceDep = Annotated[ReadingsService, Depends(get_readings_service)]
