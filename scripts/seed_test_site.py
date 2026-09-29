"""Create (or reuse) a Site row for manual MQTT subscriber testing.

Unlike scripts/mock_publish_reading.py, this reuses the app's DB session manager
and models directly rather than parsing .env itself, since it needs the ORM anyway.

Usage:
    uv run python -m scripts.seed_test_site <device_id> [name]
"""

import asyncio
import sys

from app.core.database.database import sessionmanager
from app.models import Site
from sqlalchemy import select


async def seed(device_id: str, name: str) -> None:
    async with sessionmanager.session() as db:
        site = await db.scalar(select(Site).where(Site.device_id == device_id))

        if site is not None:
            print(f"Site already exists: id={site.id} device_id={site.device_id} name={site.name}")
            return

        site = Site(
            name=name,
            device_id=device_id,
            location_lat=3.1390,
            location_lng=101.6869,
        )
        db.add(site)
        await db.commit()
        await db.refresh(site)

        print(f"Created site: id={site.id} device_id={site.device_id} name={site.name}")


def main() -> None:
    if len(sys.argv) not in (2, 3):
        print(f"Usage: {sys.argv[0]} <device_id> [name]", file=sys.stderr)
        sys.exit(1)

    device_id = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) == 3 else f"Test Site ({device_id})"

    asyncio.run(seed(device_id, name))


if __name__ == "__main__":
    main()
