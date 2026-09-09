from datetime import datetime

from pydantic import BaseModel


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
