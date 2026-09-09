from app.models import SensorReading, Site
from app.modules.readings.exceptions import UnknownDeviceError
from app.modules.readings.schemas import ReadingPayload
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

SHUNT_RESISTANCE_OHMS = 10.0


class ReadingsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record_reading(self, device_id: str, payload: ReadingPayload) -> SensorReading:
        site = await self.db.scalar(select(Site).where(Site.device_id == device_id))

        if site is None:
            raise UnknownDeviceError(device_id)

        reading = SensorReading(
            site_id=site.id,
            cell_voltage=payload.cell_voltage,
            cell_current=payload.cell_voltage / SHUNT_RESISTANCE_OHMS,
            ambient_temp=payload.ambient_temp,
            humidity=payload.humidity,
            tilt_x=payload.tilt_x,
            tilt_y=payload.tilt_y,
            tilt_z=payload.tilt_z,
            heading=payload.heading,
            device_timestamp=payload.timestamp,
        )

        self.db.add(reading)
        await self.db.commit()
        await self.db.refresh(reading)

        return reading
