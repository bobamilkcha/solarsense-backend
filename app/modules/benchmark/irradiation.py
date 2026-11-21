"""Turn a series of irradiance samples (W/m^2) into daily irradiation (kWh/m^2/day).

Each local day's samples are integrated with the trapezoid rule. Gaps longer
than MAX_GAP aren't bridged, since we can't know what the sun did in between.
A day only counts as "complete" if the integrated intervals cover most of the
daylight window — otherwise a device that ran for two hours would look like a
very shaded site — and the midday window is (almost) fully covered. An
unbridged gap counts as zero sunlight, so a dropout at noon would make a
day that passes the 90% rule look ~20% more shaded than it was. Days are in
Malaysian time (UTC+8, no DST), the target market.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Kuala_Lumpur")
MAX_GAP = timedelta(minutes=30)
# Peninsular Malaysia's sun is up roughly 07:00-19:30 year-round.
DAYLIGHT_START = time(7, 0)
DAYLIGHT_END = time(19, 0)
MIN_DAYLIGHT_COVERAGE = 0.9
# Most of the day's energy arrives in this window, so it may lose at most
# MAX_GAP to missing data (in practice: no unbridged gap inside it).
CORE_START = time(9, 0)
CORE_END = time(16, 0)


@dataclass(frozen=True)
class DayIrradiation:
    day: date
    kwh_m2: float
    daylight_coverage: float  # fraction of DAYLIGHT_START-END covered by samples
    core_missing: timedelta  # time in CORE_START-CORE_END not covered by samples

    @property
    def is_complete(self) -> bool:
        return self.daylight_coverage >= MIN_DAYLIGHT_COVERAGE and self.core_missing <= MAX_GAP


def _overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> timedelta:
    return max(min(a_end, b_end) - max(a_start, b_start), timedelta(0))


def daily_irradiation(samples: list[tuple[datetime, float]]) -> list[DayIrradiation]:
    """`samples` are (timezone-aware timestamp, irradiance W/m^2) pairs, any order."""
    by_day: dict[date, list[tuple[datetime, float]]] = defaultdict(list)
    for ts, wm2 in samples:
        local = ts.astimezone(LOCAL_TZ)
        by_day[local.date()].append((local, wm2))

    days: list[DayIrradiation] = []
    for day, day_samples in sorted(by_day.items()):
        day_samples.sort()
        window_start = datetime.combine(day, DAYLIGHT_START, LOCAL_TZ)
        window_end = datetime.combine(day, DAYLIGHT_END, LOCAL_TZ)
        core_start = datetime.combine(day, CORE_START, LOCAL_TZ)
        core_end = datetime.combine(day, CORE_END, LOCAL_TZ)

        wh_m2 = 0.0
        covered = timedelta(0)
        core_covered = timedelta(0)
        for (t1, g1), (t2, g2) in zip(day_samples, day_samples[1:], strict=False):
            gap = t2 - t1
            if gap > MAX_GAP:
                continue
            wh_m2 += (g1 + g2) / 2 * gap.total_seconds() / 3600
            covered += _overlap(t1, t2, window_start, window_end)
            core_covered += _overlap(t1, t2, core_start, core_end)

        days.append(
            DayIrradiation(
                day=day,
                kwh_m2=wh_m2 / 1000,
                daylight_coverage=covered / (window_end - window_start),
                core_missing=(core_end - core_start) - core_covered,
            )
        )
    return days
