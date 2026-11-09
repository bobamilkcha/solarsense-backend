import uuid
from collections.abc import Sequence
from datetime import timedelta

from app.models import Device, Project, Site
from app.modules.devices.exceptions import DeviceAlreadyPairedError
from app.modules.readings.exceptions import SiteNotFoundError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func


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
