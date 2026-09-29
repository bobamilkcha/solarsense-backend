import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReadingPayload(BaseModel):
    """Raw payload published by an ESP32 device to `solarsense/{device_id}/readings`.

    `device_id` is not included here — it comes from the MQTT topic path, not
    the payload body.
    """

    timestamp: datetime
    cell_voltage: float
    ambient_temp: float
    humidity: float
    tilt_x: float
    tilt_y: float
    tilt_z: float
    heading: float


class SiteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    device_id: str
    location_lat: float
    location_lng: float
    created_at: datetime


class SensorReadingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    site_id: uuid.UUID
    cell_voltage: float
    cell_current: float
    ambient_temp: float
    humidity: float
    tilt_x: float
    tilt_y: float
    tilt_z: float
    heading: float
    device_timestamp: datetime
    received_at: datetime
