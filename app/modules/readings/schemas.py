import math
import uuid
from datetime import datetime
from typing import Any

from app.modules.readings.irradiance import irradiance_wm2 as to_irradiance
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

MIN_VALID_YEAR = 2024


class ReadingPayload(BaseModel):
    """Payload an ESP32 device publishes to `solarsense/{device_id}/readings`.

    Example from the device:

        {"device": "solarsense-38BB0B71FE68", "ts": 1794226617, "v_mv": 0,
         "i_ma": 0.0, "irr": 0, "temp": 24.21, "rh": 61.95, "roll": 5.9,
         "pitch": 2.3, "heading": 267, "rssi": -59}

    The device's short field names are accepted as aliases and mapped to the
    backend's names; `v_mv` (millivolts) is converted to volts. `device`,
    `i_ma` and `irr` are ignored: the device ID comes from the MQTT topic, and
    current and irradiance are derived by the backend so there is one source
    of truth for calibration.
    """

    model_config = ConfigDict(extra="ignore")

    timestamp: datetime = Field(validation_alias=AliasChoices("timestamp", "ts"))
    cell_voltage: float
    ambient_temp: float = Field(validation_alias=AliasChoices("ambient_temp", "temp"))
    humidity: float = Field(validation_alias=AliasChoices("humidity", "rh"))
    roll: float
    pitch: float
    heading: float
    rssi: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _millivolts_to_volts(cls, data: Any) -> Any:
        if isinstance(data, dict) and "v_mv" in data and "cell_voltage" not in data:
            data = {**data}
            mv = data.pop("v_mv")
            data["cell_voltage"] = mv / 1000 if isinstance(mv, int | float) else mv
        return data

    @field_validator("timestamp")
    @classmethod
    def _clock_synced(cls, ts: datetime) -> datetime:
        # Before NTP sync the ESP32 clock counts from 1970; such a reading
        # would land decades in the past and can't be placed on a chart.
        if ts.year < MIN_VALID_YEAR:
            raise ValueError("device clock not synced (timestamp before 2024)")
        return ts


class SiteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    device_id: str | None
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
    roll: float
    pitch: float
    heading: float
    rssi: int | None
    device_timestamp: datetime
    received_at: datetime

    @computed_field
    @property
    def irradiance_wm2(self) -> float:
        """Derived from cell_current using the configured reference cell Isc."""
        return to_irradiance(self.cell_current)

    @computed_field
    @property
    def tilt_deg(self) -> float:
        """Angle of the device from horizontal, combining roll and pitch.

        0 is lying flat; this is the panel tilt angle when the device is
        mounted flush on a panel.
        """
        cos_tilt = math.cos(math.radians(self.roll)) * math.cos(math.radians(self.pitch))
        return round(math.degrees(math.acos(max(-1.0, min(1.0, cos_tilt)))), 2)
