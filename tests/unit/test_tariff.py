"""TNB domestic tariff calculator, checked against a real May 2026 bill."""

import pytest
from app.modules.reports.tariff import domestic_bill


def test_reproduces_real_bill_without_afa() -> None:
    # Real bill: 1,295 kWh. Its non-AFA lines sum to 585.37 usage charges;
    # service tax on the >600 kWh column (318.79) is 25.50; KWTBB is 9.21
    # (1.6% of energy+capacity+network = 575.37) — matching the bill's KWTBB.
    bill = domestic_bill(1295)

    assert bill.usage_charges == pytest.approx(585.37)
    assert bill.service_tax == pytest.approx(25.50)
    assert bill.kwtbb == pytest.approx(9.21)
    assert bill.total == pytest.approx(620.08)


def test_at_or_below_600_kwh_no_retail_or_service_tax() -> None:
    bill = domestic_bill(500)

    # 135.15 energy + 22.75 capacity + 64.25 network
    assert bill.usage_charges == pytest.approx(222.15)
    assert bill.service_tax == 0.0
    assert bill.kwtbb == pytest.approx(3.55)


def test_at_or_below_300_kwh_no_kwtbb() -> None:
    assert domestic_bill(300).kwtbb == 0.0


def test_afa_only_applies_above_600_kwh() -> None:
    assert domestic_bill(500, afa_rate=0.01).total == domestic_bill(500).total
    assert domestic_bill(1000, afa_rate=0.01).total > domestic_bill(1000).total


def test_energy_above_1500_kwh_uses_higher_rate() -> None:
    marginal = domestic_bill(1501).usage_charges - domestic_bill(1500).usage_charges
    # 37.03 + 4.55 + 12.85 sen for the 1,501st kWh
    assert marginal == pytest.approx(0.5443, abs=0.02)


def test_zero_and_negative_usage() -> None:
    assert domestic_bill(0).total == 0.0
    assert domestic_bill(-5).total == 0.0
