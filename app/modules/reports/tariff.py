"""TNB domestic tariff (effective 1 July 2025), for estimating bills before/after solar.

Checked line by line against a real May 2026 domestic bill: every line and
the final "Caj Semasa" match. Rules:
- Energy 27.03 sen/kWh (37.03 sen for usage above 1,500 kWh), capacity
  4.55 sen/kWh, network 12.85 sen/kWh, retail RM10/month (waived at <=600 kWh).
- AFA (fuel adjustment) only applies above 600 kWh; its rate changes monthly.
- Service tax 8% applies only to the portion above 600 kWh (incl. retail).
- KWTBB 1.6% of energy + capacity + network (not AFA/retail), above 300 kWh.
Each line is rounded to sen, as TNB does.

Not modelled: the Energy Efficiency Incentive rebate for usage <=1,000 kWh
(so post-solar bills are slightly overestimated, i.e. savings conservative),
and the all-usage service tax rule for billing periods under 28 days.
"""

from dataclasses import dataclass

ENERGY_RATE = 0.2703
ENERGY_RATE_ABOVE_1500 = 0.3703
CAPACITY_RATE = 0.0455
NETWORK_RATE = 0.1285
RETAIL_CHARGE = 10.00
SST_RATE = 0.08
KWTBB_RATE = 0.016
TAX_FREE_KWH = 600.0
ENERGY_TIER_KWH = 1500.0
KWTBB_EXEMPT_KWH = 300.0


@dataclass(frozen=True)
class DomesticBill:
    kwh: float
    usage_charges: float  # "Caj Penggunaan Bulan Semasa"
    service_tax: float
    kwtbb: float

    @property
    def total(self) -> float:
        """ "Caj Semasa" — this month's charges, before rounding adjustment."""
        return round(self.usage_charges + self.service_tax + self.kwtbb, 2)


def _r(x: float) -> float:
    return round(x + 1e-9, 2)  # half-up for the .xx5 cases floats store just below


def _variable_charges(kwh: float, total_kwh: float, offset_kwh: float, afa_rate: float) -> float:
    """Energy + capacity + network + AFA for `kwh` units starting at `offset_kwh`."""
    low = max(min(kwh, ENERGY_TIER_KWH - offset_kwh), 0.0)
    high = kwh - low
    energy = _r(low * ENERGY_RATE + high * ENERGY_RATE_ABOVE_1500)
    afa = _r(kwh * afa_rate) if total_kwh > TAX_FREE_KWH else 0.0
    return energy + afa + _r(kwh * CAPACITY_RATE) + _r(kwh * NETWORK_RATE)


def domestic_bill(kwh: float, afa_rate: float = 0.0) -> DomesticBill:
    kwh = max(kwh, 0.0)
    untaxed_kwh = min(kwh, TAX_FREE_KWH)
    taxed_kwh = kwh - untaxed_kwh
    retail = RETAIL_CHARGE if kwh > TAX_FREE_KWH else 0.0

    untaxed = _variable_charges(untaxed_kwh, kwh, 0.0, afa_rate)
    taxed = _variable_charges(taxed_kwh, kwh, untaxed_kwh, afa_rate) + retail

    energy = _r(min(kwh, ENERGY_TIER_KWH) * ENERGY_RATE) + _r(
        max(kwh - ENERGY_TIER_KWH, 0.0) * ENERGY_RATE_ABOVE_1500
    )
    kwtbb_base = energy + _r(kwh * CAPACITY_RATE) + _r(kwh * NETWORK_RATE)
    kwtbb = _r(kwtbb_base * KWTBB_RATE) if kwh > KWTBB_EXEMPT_KWH else 0.0

    return DomesticBill(
        kwh=kwh,
        usage_charges=_r(untaxed + taxed),
        service_tax=_r(taxed * SST_RATE),
        kwtbb=kwtbb,
    )
