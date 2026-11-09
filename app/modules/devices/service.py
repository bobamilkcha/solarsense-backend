import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.models import Device, Project, Site
from app.modules.devices.exceptions import (
    DeviceAlreadyPairedError,
    DeviceNotFoundError,
    MQTTUnavailableError,
)
from app.modules.devices.schemas import StatusPayload
from app.modules.readings.exceptions import SiteNotFoundError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func


class ConfigPublisher(Protocol):
    """What DevicesService needs from the MQTT client to push config to a device."""

    def is_connected(self) -> bool: ...

    def publish_config(self, device_id: str, config: dict[str, int]) -> bool: ...


class DevicesService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def mark_seen(self, device_id: str, rssi: int | None) -> None:
        """Record that a device just published (called for every MQTT message)."""
        stmt = insert(Device).values(id=device_id, last_rssi=rssi)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Device.id],
            set_={"last_seen_at": func.now(), "last_rssi": rssi},
        )
        await self.db.execute(stmt)
        await self.db.commit()

    async def apply_status(
        self, device_id: str, status: StatusPayload, *, retained: bool = False
    ) -> None:
        """Store a status message. An offline Will keeps the last known fw and interval.

        A retained message is the broker replaying old state on (re)subscribe, so
        it only counts as "seen" at the time the device stamped on it, if any.
        """
        seen_at = None if retained else func.now()
        if retained and status.ts is not None:
            seen_at = status.ts

        values: dict[str, object] = {"online": status.online, "status_at": func.now()}
        if status.online:
            values["fw"] = status.fw
            values["reported_publish_interval_s"] = status.publish_interval_s
        insert_values = {**values, "id": device_id}
        if seen_at is not None:
            insert_values["last_seen_at"] = seen_at

        stmt = insert(Device).values(**insert_values)
        update = dict(values)
        if status.online and status.fw is None:
            update.pop("fw")
        if status.online and status.publish_interval_s is None:
            update.pop("reported_publish_interval_s")
        if seen_at is not None:
            update["last_seen_at"] = func.greatest(Device.last_seen_at, seen_at)
        stmt = stmt.on_conflict_do_update(index_elements=[Device.id], set_=update)
        await self.db.execute(stmt)
        await self.db.commit()

    async def get_config(self, device_id: str, company_id: uuid.UUID | None) -> Device:
        """Desired config and reported status; the device must be paired to the caller's site."""
        return await self._authorized_device(device_id, company_id)

    async def set_desired_config(
        self,
        device_id: str,
        company_id: uuid.UUID | None,
        publisher: ConfigPublisher,
        publish_interval_s: int,
    ) -> Device:
        """Save the requested config, then publish it retained (QoS 1) to the device.

        Nothing is saved if the broker is unreachable, so the stored request
        never claims something that was not sent.
        """
        device = await self._authorized_device(device_id, company_id)
        if not publisher.is_connected():
            raise MQTTUnavailableError

        requested_at: datetime = datetime.now(UTC)
        device.desired_publish_interval_s = publish_interval_s
        device.desired_requested_at = requested_at
        await self.db.flush()

        if not publisher.publish_config(device_id, {"publish_interval_s": publish_interval_s}):
            await self.db.rollback()
            raise MQTTUnavailableError

        await self.db.commit()
        await self.db.refresh(device)
        return device

    async def _authorized_device(self, device_id: str, company_id: uuid.UUID | None) -> Device:
        stmt = (
            select(Device)
            .join(Site, Site.device_id == Device.id)
            .join(Project, Site.project_id == Project.id)
            .where(Device.id == device_id)
        )
        if company_id is not None:
            stmt = stmt.where(Project.company_id == company_id)
        device = await self.db.scalar(stmt)
        if device is None:
            raise DeviceNotFoundError
        return device

    async def list_unpaired(self, within: timedelta) -> Sequence[Device]:
        """Devices seen within `within` that no site is using, most recent first."""
        paired = select(Site.device_id).where(Site.device_id.is_not(None))
        stmt = (
            select(Device)
            .where(Device.last_seen_at >= func.now() - within)
            .where(Device.id.not_in(paired))
            .order_by(Device.last_seen_at.desc())
        )
        result = await self.db.scalars(stmt)
        return result.all()

    async def pair(self, site_id: uuid.UUID, company_id: uuid.UUID | None, device_id: str) -> Site:
        """Link `device_id` to the site, replacing any device it had before."""
        site = await self._authorized_site(site_id, company_id)
        if site.device_id == device_id:
            return site

        other = await self.db.scalar(select(Site).where(Site.device_id == device_id))
        if other is not None:
            raise DeviceAlreadyPairedError

        site.device_id = device_id
        await self.db.commit()
        await self.db.refresh(site)
        return site

    async def unpair(self, site_id: uuid.UUID, company_id: uuid.UUID | None) -> Site:
        """Release the site's device so it can be paired elsewhere. Readings stay on the site."""
        site = await self._authorized_site(site_id, company_id)
        site.device_id = None
        await self.db.commit()
        await self.db.refresh(site)
        return site

    async def _authorized_site(self, site_id: uuid.UUID, company_id: uuid.UUID | None) -> Site:
        site = await self.db.get(Site, site_id)
        if site is None:
            raise SiteNotFoundError
        if company_id is not None:
            project = await self.db.get(Project, site.project_id)
            if project is None or project.company_id != company_id:
                # 404, not 403, so other companies' site IDs aren't confirmed.
                raise SiteNotFoundError
        return site
