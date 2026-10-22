"""Pure solar feasibility maths: production, bill before/after, savings, payback.

Production per month = system kWp x irradiation (kWh/m^2, horizontal, from
PVGIS) x performance ratio x shading factor (from the device's measurements
vs the satellite). Consumption is assumed flat across the year, using the
average of the site's bills.

Of each month's production, `self_consumption_ratio` is used on-site (offsets
the bill at the full tariff); the rest is exported and credited at
`export_rate`. The bill after solar is floored at zero.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

DAYS_IN_MONTH = {1: 31, 2: 28.25, 3: 31, 4: 30, 5: 31, 6: 30,
                 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}  # fmt: skip


@dataclass(frozen=True)
class Assumptions:
    performance_ratio: float = 0.80  # inverter, wiring, soiling, heat losses
    self_consumption_ratio: float = 0.60  # share of production used on-site
    export_rate: float = 0.0  # RM/kWh credited for exported energy
    cost_per_kwp: float = 4000.0  # RM, installed
    panel_wp: float = 550.0
    degradation_per_year: float = 0.005
    lifetime_years: int = 25


@dataclass(frozen=True)
class MonthResult:
    month: int
    production_kwh: float
    self_consumed_kwh: float
    exported_kwh: float
    bill_before_rm: float
    bill_after_rm: float

    @property
    def savings_rm(self) -> float:
        return self.bill_before_rm - self.bill_after_rm


@dataclass(frozen=True)
class FeasibilityResult:
    system_kwp: float
    panel_count: int
    system_cost_rm: float
    months: list[MonthResult]

    @property
    def annual_production_kwh(self) -> float:
        return sum(m.production_kwh for m in self.months)

    @property
    def annual_savings_rm(self) -> float:
        return sum(m.savings_rm for m in self.months)

    @property
    def payback_years(self) -> float | None:
        savings = self.annual_savings_rm
        return self.system_cost_rm / savings if savings > 0 else None


def yield_per_kwp(irradiation: dict[int, float], shading_factor: float, pr: float) -> float:
    """Annual kWh produced per kWp installed."""
    return sum(irradiation.values()) * pr * shading_factor


def recommend_kwp(
    monthly_kwh: float, irradiation: dict[int, float], shading_factor: float, a: Assumptions
) -> float:
    """Size to cover annual consumption, rounded down to whole panels (min 1)."""
    annual_yield = yield_per_kwp(irradiation, shading_factor, a.performance_ratio)
    if annual_yield <= 0:
        return a.panel_wp / 1000
    kwp = monthly_kwh * 12 / annual_yield
    panels = max(math.floor(kwp * 1000 / a.panel_wp), 1)
    return panels * a.panel_wp / 1000


def lifetime_net_savings(result: FeasibilityResult, a: Assumptions) -> float:
    """Total savings over the system's life minus its cost. Production degrades
    yearly; tariffs are held flat (conservative)."""
    total = sum(
        result.annual_savings_rm * (1 - a.degradation_per_year) ** year
        for year in range(a.lifetime_years)
    )
    return total - result.system_cost_rm


def evaluate(
    *,
    monthly_kwh: float,
    irradiation: dict[int, float],
    shading_factor: float,
    bill_for_kwh: Callable[[float], float],
    system_kwp: float,
    a: Assumptions,
) -> FeasibilityResult:
    months: list[MonthResult] = []
    for month in range(1, 13):
        # Scale the flat 30.44-day consumption to this month's length.
        consumption = monthly_kwh * DAYS_IN_MONTH[month] / (365.25 / 12)
        production = system_kwp * irradiation.get(month, 0.0) * a.performance_ratio
        production *= shading_factor
        self_used = min(production * a.self_consumption_ratio, consumption)
        exported = production - self_used

        before = bill_for_kwh(consumption)
        after = max(bill_for_kwh(consumption - self_used) - exported * a.export_rate, 0.0)
        months.append(
            MonthResult(
                month=month,
                production_kwh=production,
                self_consumed_kwh=self_used,
                exported_kwh=exported,
                bill_before_rm=before,
                bill_after_rm=after,
            )
        )

    panels = max(round(system_kwp * 1000 / a.panel_wp), 1)
    return FeasibilityResult(
        system_kwp=system_kwp,
        panel_count=panels,
        system_cost_rm=system_kwp * a.cost_per_kwp,
        months=months,
    )
