from typing import Annotated

from app.core.deps import DBSession
from app.modules.devices.exceptions import MQTTUnavailableError
from app.modules.devices.service import ConfigPublisher, DevicesService
from fastapi import Depends, Request


def get_devices_service(db: DBSession) -> DevicesService:
    return DevicesService(db)


def get_config_publisher(request: Request) -> ConfigPublisher:
    """The app's shared MQTT client (set in `lifespan`)."""
    publisher = getattr(request.app.state, "mqtt", None)
    if publisher is None:
        raise MQTTUnavailableError
    return publisher


DevicesServiceDep = Annotated[DevicesService, Depends(get_devices_service)]
ConfigPublisherDep = Annotated[ConfigPublisher, Depends(get_config_publisher)]
