"""Publish (or insert) realistic mock readings for a device over a date range.

The device_id must already exist as a Site (see scripts/seed_test_site.py).

Examples:
    # Last 7 days through MQTT (backend must be running: `mise run dev`)
    uv run python -m scripts.mock_publish_series 01 --days 7

    # A full year straight into the DB (seconds instead of ~20 min of MQTT)
    uv run python -m scripts.mock_publish_series 01 --years 1 --via db

    # An explicit range, a shaded site, 5-minute readings
    uv run python -m scripts.mock_publish_series 01 --start 2026-03-01 --end 2026-04-01 \\
        --shade 0.7 --interval 5 --via db

    # Just preview what would be generated
    uv run python -m scripts.mock_publish_series 01 --months 3 --dry-run

Range: give one of --days/--weeks/--months/--years (counted back from --end,
which defaults to now), or --start [--end]. Dates are Malaysian local time.

`--via mqtt` (default) sends each reading through the broker, exercising the
real ingestion path. Messages sent while the backend isn't running are lost.
`--via db` writes rows directly (same derived cell_current as ingestion); use
`--replace` to clear the site's existing readings in that range first, so
re-runs don't double up.
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import dotenv_values

from scripts.mock_weather import LOCAL_TZ, MockOptions, MockReading, daily_totals, generate

ENV = dotenv_values(Path(__file__).resolve().parent.parent / ".env")
DB_BATCH = 5000


def _months_back(d: datetime, months: int) -> datetime:
    month_index = d.year * 12 + (d.month - 1) - months
    year, month = divmod(month_index, 12)
    month += 1
    # Clamp e.g. 31 March - 1 month to 28/29 Feb.
    next_month = date(year + (month == 12), month % 12 + 1, 1)
    last_day = (next_month - timedelta(days=1)).day
    return d.replace(year=year, month=month, day=min(d.day, last_day))


def _parse_local(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=LOCAL_TZ) if parsed.tzinfo is None else parsed


def _resolve_range(args: argparse.Namespace) -> tuple[datetime, datetime]:
    interval = timedelta(minutes=args.interval)
    end = _parse_local(args.end) if args.end else datetime.now(LOCAL_TZ)
    # Align to the interval so runs line up with each other.
    epoch = datetime(2000, 1, 1, tzinfo=LOCAL_TZ)
    end = epoch + ((end - epoch) // interval) * interval

    if args.start:
        start = _parse_local(args.start)
    elif args.days:
        start = end - timedelta(days=args.days)
    elif args.weeks:
        start = end - timedelta(weeks=args.weeks)
    elif args.months:
        start = _months_back(end, args.months)
    elif args.years:
        start = _months_back(end, 12 * args.years)
    else:
        start = end - timedelta(days=7)

    if start >= end:
        sys.exit("error: start must be before end")
    return start, end


def _summary(readings: list[MockReading], opts: MockOptions) -> None:
    totals = daily_totals(readings, opts.interval)
    if not readings:
        print("No readings in range.")
        return
    print(
        f"{len(readings):,} readings over {len(totals)} day(s), "
        f"{readings[0].timestamp:%Y-%m-%d %H:%M} -> {readings[-1].timestamp:%Y-%m-%d %H:%M} (MYT)"
    )
    # Skip partial days at the range edges (e.g. a range ending at "now"),
    # which would drag the min/avg down.
    edges = {readings[0].timestamp.date(), readings[-1].timestamp.date()}
    first, last = readings[0].timestamp, readings[-1].timestamp
    full = {
        d: v
        for d, v in totals.items()
        if d not in edges
        or (d == first.date() and first.hour < 7 and (d != last.date() or last.hour >= 19))
        or (d == last.date() and last.hour >= 19 and d != first.date())
    }
    if not full:
        print("No full days in range, so no daily sunlight summary.")
        return
    print(
        f"Sunlight per full day ({len(full)}): avg {statistics.mean(full.values()):.2f} kWh/m², "
        f"min {min(full.values()):.2f}, max {max(full.values()):.2f}"
    )


def _publish_mqtt(device_id: str, readings: list[MockReading], rate: float) -> None:
    import paho.mqtt.client as mqtt

    topic = f"solarsense/{device_id}/readings"
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    if username := ENV.get("MQTT_USERNAME"):
        client.username_pw_set(username, ENV.get("MQTT_PASSWORD", ""))
    if (ENV.get("MQTT_USE_TLS") or "true").lower() == "true":
        client.tls_set()
    client.max_inflight_messages_set(100)
    client.connect(
        ENV.get("MQTT_BROKER_HOST") or "localhost", int(ENV.get("MQTT_BROKER_PORT") or 8883)
    )
    client.loop_start()

    print(f"Publishing to {topic} at up to {rate:g} msg/s (Ctrl+C to stop)...")
    started = time.monotonic()
    last = None
    try:
        for i, reading in enumerate(readings, start=1):
            last = client.publish(topic, json.dumps(reading.payload()), qos=1)
            # Throttle to `rate` messages per second.
            delay = started + i / rate - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            if i % 500 == 0 or i == len(readings):
                print(f"  {i:,}/{len(readings):,}", flush=True)
        if last is not None:
            last.wait_for_publish(timeout=30)
    finally:
        client.loop_stop()
        client.disconnect()
    print("Done. Check the backend logs for mqtt_unknown_device if nothing shows up.")


async def _insert_db(
    device_id: str, readings: list[MockReading], start: datetime, end: datetime, replace: bool
) -> None:
    # Imported here so --via mqtt / --dry-run don't need the app or a database.
    from app.core.database.database import sessionmanager
    from app.models import SensorReading, Site
    from app.modules.readings.service import SHUNT_RESISTANCE_OHMS
    from sqlalchemy import delete, select

    async with sessionmanager.session() as db:
        site = await db.scalar(select(Site).where(Site.device_id == device_id))
        if site is None:
            sys.exit(
                f"error: no site with device_id={device_id!r}. "
                f"Create one first: uv run python -m scripts.seed_test_site {device_id}"
            )

        if replace:
            result = await db.execute(
                delete(SensorReading).where(
                    SensorReading.site_id == site.id,
                    SensorReading.device_timestamp >= start,
                    SensorReading.device_timestamp < end,
                )
            )
            print(f"Deleted {getattr(result, 'rowcount', 0):,} existing reading(s) in range.")

        for i in range(0, len(readings), DB_BATCH):
            db.add_all(
                SensorReading(
                    site_id=site.id,
                    cell_voltage=r.cell_voltage,
                    cell_current=r.cell_voltage / SHUNT_RESISTANCE_OHMS,
                    ambient_temp=r.ambient_temp,
                    humidity=r.humidity,
                    tilt_x=r.tilt_x,
                    tilt_y=r.tilt_y,
                    tilt_z=r.tilt_z,
                    heading=r.heading,
                    device_timestamp=r.timestamp,
                )
                for r in readings[i : i + DB_BATCH]
            )
            await db.commit()
            print(f"  {min(i + DB_BATCH, len(readings)):,}/{len(readings):,}", flush=True)

    await sessionmanager.close()
    print(f"Inserted into site {site.id} ({site.name}).")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish realistic mock readings for a device over a date range.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("device_id")
    span = parser.add_mutually_exclusive_group()
    span.add_argument("--days", type=int)
    span.add_argument("--weeks", type=int)
    span.add_argument("--months", type=int)
    span.add_argument("--years", type=int)
    span.add_argument("--start", help="Start date/time, e.g. 2026-03-01 or 2026-03-01T06:00")
    parser.add_argument("--end", help="End date/time (exclusive); default now")
    parser.add_argument(
        "--interval", type=float, default=10, help="Minutes between readings (default 10)"
    )
    parser.add_argument("--via", choices=["mqtt", "db"], default="mqtt")
    parser.add_argument(
        "--rate", type=float, default=50, help="MQTT messages per second (default 50)"
    )
    parser.add_argument(
        "--replace", action="store_true", help="--via db: delete existing readings in range first"
    )
    parser.add_argument(
        "--shade",
        type=float,
        default=1.0,
        help="Fraction of sun reaching the cell, 0-1 (default 1)",
    )
    parser.add_argument(
        "--tilt", type=float, default=0.0, help="Cell tilt in degrees (default 0 = flat)"
    )
    parser.add_argument("--daylight-only", action="store_true", help="Skip night-time readings")
    parser.add_argument(
        "--isc",
        type=float,
        help="Reference cell Isc in amps (default: .env REFERENCE_CELL_ISC_A or 0.22)",
    )
    parser.add_argument("--seed", type=int, help="Random seed for repeatable data")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be generated, send nothing"
    )
    args = parser.parse_args()

    if not 0 <= args.shade <= 1:
        parser.error("--shade must be between 0 and 1")
    if args.interval <= 0 or args.rate <= 0:
        parser.error("--interval and --rate must be positive")
    if args.replace and args.via != "db":
        parser.error("--replace only applies to --via db")

    opts = MockOptions(
        interval=timedelta(minutes=args.interval),
        isc_a=args.isc or float(ENV.get("REFERENCE_CELL_ISC_A") or 0.22),
        shade_factor=args.shade,
        tilt_deg=args.tilt,
        daylight_only=args.daylight_only,
        seed=args.seed,
    )
    start, end = _resolve_range(args)
    readings = list(generate(start, end, opts))
    _summary(readings, opts)

    if args.dry_run or not readings:
        return

    if args.via == "mqtt":
        minutes = len(readings) / args.rate / 60
        if minutes > 5:
            print(
                f"Note: ~{minutes:.0f} min at {args.rate:g} msg/s. "
                "For big ranges, --via db is much faster."
            )
        _publish_mqtt(args.device_id, readings, args.rate)
    else:
        asyncio.run(_insert_db(args.device_id, readings, start, end, args.replace))


if __name__ == "__main__":
    main()
