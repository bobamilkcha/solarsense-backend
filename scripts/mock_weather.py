"""Generate realistic mock SolarSense readings for Kuala Lumpur.

Pure data generation (no MQTT, no DB) so it can be reused and dry-run. The
model is deliberately simple but shaped like real data:

- Sun up ~07:10-19:20 local time, solar noon ~13:15 (KL is at 101.7°E but on
  UTC+8, so noon is late). Clear-sky peak ~1000 W/m² on a flat surface.
- Each day is clear, partly cloudy or overcast, with a chance of an
  afternoon thunderstorm.
- Clouds drift sample to sample rather than jumping randomly.
- Temperature and humidity follow the day and react to sunshine.

Calibrated to PVGIS: each month's mix of clear/cloudy days is chosen so the
long-run average matches PVGIS's figure for Kuala Lumpur. So an unshaded mock
site scores ~1.0 on the benchmark ratio, and `shade_factor=0.7` scores ~0.7.
Individual days and short ranges still vary a lot, as real weather does.
"""

import math
import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Kuala_Lumpur")
SHUNT_OHMS = 10.0  # matches app.modules.readings.service.SHUNT_RESISTANCE_OHMS

SOLAR_NOON_HOURS = 13.25
HALF_DAY_HOURS = 6.1
CLEAR_SKY_PEAK_WM2 = 1000.0

STORM_CHANCE = 0.30

# PVGIS-ERA5 long-term average horizontal irradiation for Kuala Lumpur
# (3.139, 101.687), kWh/m²/day by month. Fetched 2026-10-23 via the app's
# benchmark client (1,938 kWh/m² per year).
PVGIS_KL_DAILY = {1: 5.21, 2: 6.00, 3: 5.97, 4: 5.70, 5: 5.24, 6: 5.14,
                  7: 5.16, 8: 5.44, 9: 5.41, 10: 5.22, 11: 4.64, 12: 4.60}  # fmt: skip

# Average kWh/m² a day of each sky type under this model (including the storm
# chance), measured by simulating 4,000 days of each.
_CLEAR_KWH, _PARTLY_KWH, _OVERCAST_KWH = 6.396, 4.665, 2.274
_PARTLY_SHARE_OF_CLOUDY = 0.75  # cloudy days are 3 partly : 1 overcast


def _sky_odds(target_kwh: float) -> tuple[float, float, float]:
    """(clear, partly, overcast) probabilities whose average hits target_kwh."""
    cloudy_kwh = _PARTLY_SHARE_OF_CLOUDY * _PARTLY_KWH + (1 - _PARTLY_SHARE_OF_CLOUDY) * (
        _OVERCAST_KWH
    )
    if target_kwh >= cloudy_kwh:
        clear = min((target_kwh - cloudy_kwh) / (_CLEAR_KWH - cloudy_kwh), 1.0)
        return (
            clear,
            (1 - clear) * _PARTLY_SHARE_OF_CLOUDY,
            (1 - clear) * (1 - _PARTLY_SHARE_OF_CLOUDY),
        )
    # Duller than the cloudy mix: no clear days, shift toward overcast.
    partly = max((target_kwh - _OVERCAST_KWH) / (_PARTLY_KWH - _OVERCAST_KWH), 0.0)
    return 0.0, partly, 1 - partly


SKY_ODDS = {m: _sky_odds(kwh) for m, kwh in PVGIS_KL_DAILY.items()}


@dataclass(frozen=True)
class MockOptions:
    interval: timedelta = timedelta(minutes=10)
    isc_a: float = 0.22  # reference cell short-circuit current at 1000 W/m²
    shade_factor: float = 1.0  # 1.0 = unshaded; 0.7 = site gets 70% of the sun
    tilt_deg: float = 0.0  # 0 = cell lying flat
    heading_deg: float = 180.0
    daylight_only: bool = False
    seed: int | None = None


@dataclass(frozen=True)
class MockReading:
    timestamp: datetime  # timezone-aware, local time
    irradiance_wm2: float
    cell_voltage: float
    ambient_temp: float
    humidity: float
    tilt_x: float
    tilt_y: float
    tilt_z: float
    heading: float

    def payload(self) -> dict[str, object]:
        """The JSON body an ESP32 would publish."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "cell_voltage": self.cell_voltage,
            "ambient_temp": self.ambient_temp,
            "humidity": self.humidity,
            "tilt_x": self.tilt_x,
            "tilt_y": self.tilt_y,
            "tilt_z": self.tilt_z,
            "heading": self.heading,
        }


def _sun_shape(hours: float) -> float:
    """0 at night, rising to 1 at solar noon."""
    x = (hours - SOLAR_NOON_HOURS) / HALF_DAY_HOURS
    if abs(x) >= 1:
        return 0.0
    return math.cos(x * math.pi / 2) ** 1.3


def _warmth_shape(hours: float) -> float:
    """Daily temperature curve, 0-1: coolest ~06:00, warmest ~14:30.

    Warms quickly through the morning (8.5 h) and cools slowly through the
    evening and night (15.5 h), as in KL.
    """
    if 6.0 <= hours < 14.5:
        return (1 - math.cos(math.pi * (hours - 6.0) / 8.5)) / 2
    since_peak = (hours - 14.5) % 24
    return (1 + math.cos(math.pi * since_peak / 15.5)) / 2


class _Day:
    """One day's weather: sky type, optional storm, and a drifting cloud level."""

    def __init__(self, day: date, rng: random.Random) -> None:
        self.rng = rng
        clear, partly, _ = SKY_ODDS[day.month]
        roll = rng.random()
        if roll < clear:
            self.low, self.high = 0.85, 1.0
        elif roll < clear + partly:
            self.low, self.high = 0.35, 1.0
        else:
            self.low, self.high = 0.15, 0.5
        self.storm_start = rng.uniform(14.5, 17.0) if rng.random() < STORM_CHANCE else None
        self.storm_hours = rng.uniform(1.0, 2.5)
        self.cloud = rng.uniform(self.low, self.high)

    def cloud_factor(self, hours: float) -> float:
        # Drift toward a new random target so clouds pass gradually.
        target = self.rng.uniform(self.low, self.high)
        self.cloud = 0.7 * self.cloud + 0.3 * target
        if self.storm_start is not None and (
            self.storm_start <= hours < self.storm_start + self.storm_hours
        ):
            return min(self.cloud, self.rng.uniform(0.08, 0.25))
        return self.cloud


def generate(start: datetime, end: datetime, opts: MockOptions) -> Iterator[MockReading]:
    """Readings every `opts.interval` from `start` (inclusive) to `end` (exclusive)."""
    rng = random.Random(opts.seed)
    t = start.astimezone(LOCAL_TZ)
    end = end.astimezone(LOCAL_TZ)
    weather: _Day | None = None
    weather_day: date | None = None

    while t < end:
        if t.date() != weather_day:
            weather_day = t.date()
            weather = _Day(weather_day, rng)
        assert weather is not None

        hours = t.hour + t.minute / 60 + t.second / 3600
        sun = _sun_shape(hours)
        cloud = weather.cloud_factor(hours)

        if opts.daylight_only and sun == 0:
            t += opts.interval
            continue

        tilt_loss = math.cos(math.radians(opts.tilt_deg))
        irradiance = CLEAR_SKY_PEAK_WM2 * sun * cloud * opts.shade_factor * tilt_loss
        current = irradiance / 1000 * opts.isc_a
        # ADC noise: a few mV, so night readings sit near (not exactly at) zero.
        voltage = max(current * SHUNT_OHMS + rng.gauss(0, 0.003), 0.0)

        sunny = sun * cloud
        temp = 24.5 + 7.0 * _warmth_shape(hours) + 2.5 * sunny + rng.gauss(0, 0.3)
        humidity = 95 - 30 * _warmth_shape(hours) - 8 * sunny + rng.gauss(0, 1.5)

        yield MockReading(
            timestamp=t,
            irradiance_wm2=irradiance,
            cell_voltage=round(voltage, 4),
            ambient_temp=round(temp, 2),
            humidity=round(min(max(humidity, 40.0), 100.0), 2),
            tilt_x=round(opts.tilt_deg + rng.gauss(0, 0.2), 2),
            tilt_y=round(rng.gauss(0, 0.2), 2),
            tilt_z=round(90.0 - opts.tilt_deg + rng.gauss(0, 0.2), 2),
            heading=round((opts.heading_deg + rng.gauss(0, 0.5)) % 360, 2),
        )
        t += opts.interval


def daily_totals(readings: list[MockReading], interval: timedelta) -> dict[date, float]:
    """kWh/m² per local day (simple sum; good enough for a summary)."""
    hours = interval.total_seconds() / 3600
    totals: dict[date, float] = {}
    for r in readings:
        totals[r.timestamp.date()] = totals.get(r.timestamp.date(), 0.0) + (
            r.irradiance_wm2 * hours / 1000
        )
    return totals
