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

        {"device": "solarsense-38BB0B71FE68", "ts": 1794226353, "v_mv": 1850,
         "temp": 24.22, "rh": 61.81, "roll": 5.9, "pitch": 2.5, "heading": 267,
         "rssi": -71}

    The device's short field names are accepted as aliases and mapped to the
    backend's names; `v_mv` (millivolts) is converted to volts. `ts` is null
    until the device's clock syncs, and `temp`, `rh`, `roll`, `pitch` and
    `heading` are null when that sensor failed. `device` is ignored (the ID
    comes from the MQTT topic), as are `i_ma` and `irr` from older firmware:
    current and irradiance are derived by the backend so there is one source of
    truth for calibration.
    """

    model_config = ConfigDict(extra="ignore")

    # None means the device had no valid clock: the server receive time is used.
    timestamp: datetime | None = Field(
        default=None, validation_alias=AliasChoices("timestamp", "ts")
    )
    cell_voltage: float
    ambient_temp: float | None = Field(
        default=None, validation_alias=AliasChoices("ambient_temp", "temp")
    )
    humidity: float | None = Field(default=None, validation_alias=AliasChoices("humidity", "rh"))
    roll: float | None = None
    pitch: float | None = None
    heading: float | None = None
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
    def _clock_synced(cls, ts: datetime | None) -> datetime | None:
        # Before NTP sync the ESP32 clock counts from 1970; such a reading
        # would land decades in the past and can't be placed on a chart, so
        # treat it as "no timestamp" and let the server stamp it.
        if ts is not None and ts.year < MIN_VALID_YEAR:
            return None
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
    ambient_temp: float | None
    humidity: float | None
    roll: float | None
    pitch: float | None
    heading: float | None
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
    def tilt_deg(self) -> float | None:
        """Angle of the device from horizontal, combining roll and pitch.

        0 is lying flat; this is the panel tilt angle when the device is
        mounted flush on a panel. Null if the orientation sensor failed.
        """
        if self.roll is None or self.pitch is None:
            return None
        cos_tilt = math.cos(math.radians(self.roll)) * math.cos(math.radians(self.pitch))
        return round(math.degrees(math.acos(max(-1.0, min(1.0, cos_tilt)))), 2)
