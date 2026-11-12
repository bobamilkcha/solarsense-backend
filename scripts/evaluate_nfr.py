"""Measure NFR3 (ingestion latency) and NFR6 (accuracy vs satellite) from stored readings.

NFR3: latency = received_at - device_timestamp for each reading. Needs the
device clock to be NTP-synced. Readings with latency <= 0 are skipped: they are
either readings with no device timestamp (the backend fills in its own time) or
clock skew, and would make latency look better than it is.

NFR6: each complete local day's irradiation (same integration as the benchmark
endpoint) is paired with NASA POWER's satellite estimate for that same day
(ALLSKY_SFC_SW_DWN, kWh/m^2/day, local solar time). PVGIS isn't used here
because it only has long-term monthly averages, not same-period daily values.
NASA POWER data lags about a week, so recent days have no satellite value yet.

    nRMSE = RMSE / mean(satellite) * 100
    nMBE  = mean(device - satellite) / mean(satellite) * 100   (sign = bias)

Usage:
    uv run python -m scripts.evaluate_nfr <device_id or site_id> --start 2026-10-01 --end 2026-11-01
        [--latency-limit 5] [--nrmse-limit 15]
--start is inclusive, --end is exclusive, both in Malaysian time.
"""

import argparse
import asyncio
import math
import statistics
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from app.core.config.app_config import app_config
from app.core.database.database import sessionmanager
from app.models import SensorReading, Site
from app.modules.benchmark.irradiation import LOCAL_TZ, daily_irradiation
from app.modules.readings.irradiance import irradiance_wm2
from sqlalchemy import select

NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
NASA_FILL_VALUE = -999.0


@dataclass(frozen=True)
class LatencyStats:
    count: int
    skipped: int
    median_s: float
    p95_s: float
    max_s: float
    within_limit_pct: float


@dataclass(frozen=True)
class AccuracyStats:
    days: int
    mean_device: float
    mean_satellite: float
    rmse: float
    nrmse_pct: float
    nmbe_pct: float


def latency_stats(latencies_s: list[float], limit_s: float) -> LatencyStats | None:
    valid = sorted(x for x in latencies_s if x > 0)
    if not valid:
        return None
    p95_index = max(math.ceil(0.95 * len(valid)) - 1, 0)
    return LatencyStats(
        count=len(valid),
        skipped=len(latencies_s) - len(valid),
        median_s=statistics.median(valid),
        p95_s=valid[p95_index],
        max_s=valid[-1],
        within_limit_pct=100 * sum(x <= limit_s for x in valid) / len(valid),
    )


def accuracy_stats(pairs: list[tuple[float, float]]) -> AccuracyStats | None:
    """`pairs` are (device, satellite) daily irradiation in kWh/m^2/day."""
    if not pairs:
        return None
    errors = [d - s for d, s in pairs]
    mean_sat = statistics.fmean(s for _, s in pairs)
    rmse = math.sqrt(statistics.fmean(e * e for e in errors))
    return AccuracyStats(
        days=len(pairs),
        mean_device=statistics.fmean(d for d, _ in pairs),
        mean_satellite=mean_sat,
        rmse=rmse,
        nrmse_pct=100 * rmse / mean_sat,
        nmbe_pct=100 * statistics.fmean(errors) / mean_sat,
    )


def fetch_nasa_daily(lat: float, lng: float, start: date, end_inclusive: date) -> dict[date, float]:
    response = httpx.get(
        NASA_POWER_URL,
        params={
            "parameters": "ALLSKY_SFC_SW_DWN",
            "community": "RE",
            "latitude": lat,
            "longitude": lng,
            "start": start.strftime("%Y%m%d"),
            "end": end_inclusive.strftime("%Y%m%d"),
            "format": "JSON",
            "time-standard": "LST",
        },
        timeout=30.0,
    )
    response.raise_for_status()
    values = response.json()["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]
    return {
        datetime.strptime(day, "%Y%m%d").date(): float(v)
        for day, v in values.items()
        if float(v) != NASA_FILL_VALUE
    }


async def load(site_ref: str, start: datetime, end: datetime) -> tuple[Site, Sequence[Any]]:
    async with sessionmanager.session() as db:
        try:
            site = await db.get(Site, uuid.UUID(site_ref))
        except ValueError:
            site = await db.scalar(select(Site).where(Site.device_id == site_ref))
        if site is None:
            sys.exit(f"No site found for {site_ref!r}")
        rows = (
            await db.execute(
                select(
                    SensorReading.device_timestamp,
                    SensorReading.received_at,
                    SensorReading.cell_current,
                )
                .where(
                    SensorReading.site_id == site.id,
                    SensorReading.device_timestamp >= start,
                    SensorReading.device_timestamp < end,
                )
                .order_by(SensorReading.device_timestamp)
            )
        ).all()
    await sessionmanager.close()
    return site, rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure NFR3 latency and NFR6 accuracy.")
    parser.add_argument("site", help="device_id or site UUID")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--latency-limit", type=float, default=5.0, help="seconds (NFR3)")
    parser.add_argument("--nrmse-limit", type=float, default=None, help="percent (NFR6)")
    args = parser.parse_args()

    start = datetime.combine(args.start, datetime.min.time(), LOCAL_TZ)
    end = datetime.combine(args.end, datetime.min.time(), LOCAL_TZ)
    site, rows = asyncio.run(load(args.site, start, end))
    print(f"Site {site.name} ({site.device_id}), {args.start} to {args.end}: {len(rows)} readings")

    print("\nNFR3 - ingestion latency (received_at - device timestamp)")
    lat = latency_stats(
        [(r.received_at - r.device_timestamp).total_seconds() for r in rows], args.latency_limit
    )
    if lat is None:
        print("  No readings with a usable device timestamp.")
    else:
        verdict = "PASS" if lat.p95_s <= args.latency_limit else "FAIL"
        print(f"  readings used: {lat.count} (skipped {lat.skipped} with latency <= 0)")
        print(f"  median {lat.median_s:.2f} s, p95 {lat.p95_s:.2f} s, max {lat.max_s:.2f} s")
        print(f"  within {args.latency_limit:g} s: {lat.within_limit_pct:.1f}%")
        print(f"  {verdict} (p95 <= {args.latency_limit:g} s)")
        if lat.median_s > 3600:
            print("  Note: latency over an hour usually means backfilled/mock data, not live.")

    print("\nNFR6 - daily irradiation vs NASA POWER satellite (same days)")
    isc = app_config.REFERENCE_CELL_ISC_A
    samples = [(r.device_timestamp, irradiance_wm2(float(r.cell_current), isc)) for r in rows]
    all_days = daily_irradiation(samples)
    days = [d for d in all_days if d.is_complete]
    satellite = fetch_nasa_daily(
        float(site.location_lat), float(site.location_lng), args.start, args.end - timedelta(days=1)
    )
    pairs = [(d.kwh_m2, satellite[d.day]) for d in days if d.day in satellite]
    print(f"  complete device days: {len(days)}, with satellite data: {len(pairs)}")
    for d in all_days:
        sat = satellite.get(d.day)
        sat_text = f"{sat:.2f}" if sat is not None else " n/a"
        note = "" if d.is_complete else "  (skipped: under 90% of 07:00-19:00 covered)"
        print(
            f"    {d.day}  coverage {d.daylight_coverage:4.0%}  device {d.kwh_m2:.2f}"
            f"  satellite {sat_text} kWh/m^2{note}"
        )
    acc = accuracy_stats(pairs)
    if acc is None:
        print("  No days to compare.")
    else:
        print(
            f"  mean device {acc.mean_device:.2f}, satellite {acc.mean_satellite:.2f} kWh/m^2/day"
        )
        print(f"  RMSE {acc.rmse:.3f}, nRMSE {acc.nrmse_pct:.1f}%, nMBE {acc.nmbe_pct:+.1f}%")
        if args.nrmse_limit is not None:
            verdict = "PASS" if acc.nrmse_pct <= args.nrmse_limit else "FAIL"
            print(f"  {verdict} (nRMSE <= {args.nrmse_limit:g}%)")
        print(f"  Reference cell Isc used: {isc * 1000:.0f} mA (calibrate before reporting)")


if __name__ == "__main__":
    main()
