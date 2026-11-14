"""TNB domestic tariff (effective 1 July 2025), for estimating bills before/after solar.

Checked line by line against a real May 2026 domestic bill: every line and
the final "Caj Semasa" match. Rules:
- Energy 27.03 sen/kWh (37.03 sen for usage above 1,500 kWh), capacity
  4.55 sen/kWh, network 12.85 sen/kWh, retail RM10/month (waived at <=600 kWh).
- AFA (fuel adjustment) only applies above 600 kWh; its rate changes monthly.
- Service tax 8% applies only to the portion above 600 kWh (incl. retail).
- KWTBB 1.6% of energy + capacity + network (not AFA/retail), above 300 kWh,
  calculated after the EEI rebate is deducted.
- Energy Efficiency Incentive (EEI) rebate for usage <=1,000 kWh: one sen/kWh
  rate, chosen by the month's total usage, applied to every kWh (e.g. 380 kWh
  x 17 sen = RM64.60). The rebate shrinks as usage rises and is zero above
  1,000 kWh.
Each line is rounded to sen, as TNB does.

Source: TNB "Guide to Electricity Tariff" (rates effective 1 July 2025). Its
Table 2 gives the EEI bands and "EEI (RM) = monthly consumption (kWh) x rate".
Its worked 625 kWh bill shows the rebate split by kWh between the untaxed
(first 600 kWh) and taxed columns, each rounded to sen, with service tax on
the taxed column after the rebate. The model reproduces that bill, and six
real domestic bills from 354 to 431 kWh (Apr-Sep 2026) to the sen, once a
late-payment surcharge on one is excluded.

Not modelled: the all-usage service tax rule for billing periods under 28 days.
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

# (upper kWh limit of the band, rebate in RM/kWh), from the July 2025 tariff.
EEI_BANDS: tuple[tuple[float, float], ...] = (
    (200, 0.250), (250, 0.245), (300, 0.225), (350, 0.210), (400, 0.170),
    (450, 0.145), (500, 0.120), (550, 0.105), (600, 0.090), (650, 0.075),
    (700, 0.055), (750, 0.045), (800, 0.040), (850, 0.025), (900, 0.010),
    (1000, 0.005),
)  # fmt: skip


@dataclass(frozen=True)
class DomesticBill:
    kwh: float
    usage_charges: float  # "Caj Penggunaan Bulan Semasa", before the EEI rebate
    eei: float  # Energy Efficiency Incentive rebate, as a positive amount
    service_tax: float
    kwtbb: float

    @property
    def total(self) -> float:
        """ "Caj Semasa" — this month's charges, before rounding adjustment."""
        return round(self.usage_charges - self.eei + self.service_tax + self.kwtbb, 2)


def _r(x: float) -> float:
    return round(x + 1e-9, 2)  # half-up for the .xx5 cases floats store just below


def eei_rate(kwh: float) -> float:
    """EEI rebate in RM/kWh for a month's total usage; 0 above 1,000 kWh."""
    for limit, rate in EEI_BANDS:
        if kwh <= limit:
            return rate
    return 0.0


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
    # One rate for the month's total usage, applied per column as TNB bills it.
    rate = eei_rate(kwh)
    taxed_eei = _r(taxed_kwh * rate)
    eei = _r(untaxed_kwh * rate) + taxed_eei

    kwtbb_base = energy + _r(kwh * CAPACITY_RATE) + _r(kwh * NETWORK_RATE) - eei
    kwtbb = _r(kwtbb_base * KWTBB_RATE) if kwh > KWTBB_EXEMPT_KWH else 0.0

    return DomesticBill(
        kwh=kwh,
        usage_charges=_r(untaxed + taxed),
        eei=eei,
        service_tax=_r((taxed - taxed_eei) * SST_RATE),
        kwtbb=kwtbb,
    )
