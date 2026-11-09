from typing import Annotated

from app.core.deps import DBSession
from app.modules.devices.service import DevicesService
from fastapi import Depends


def get_devices_service(db: DBSession) -> DevicesService:
    return DevicesService(db)


DevicesServiceDep = Annotated[DevicesService, Depends(get_devices_service)]
