"""TNB domestic tariff calculator, checked against real 2026 bills."""

import pytest
from app.modules.reports.tariff import domestic_bill, eei_rate


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
    # EEI 500 x 12 sen = 60.00; KWTBB 1.6% of (222.15 - 60.00)
    assert bill.eei == pytest.approx(60.00)
    assert bill.kwtbb == pytest.approx(2.59)


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


@pytest.mark.parametrize(
    ("kwh", "caj_semasa"),
    [
        # Real domestic bills (Caj Semasa), Apr-Sep 2026, one household.
        (354, 98.66),
        (362, 100.89),
        (389, 108.42),
        (407, 123.76),
        (431, 131.05),
    ],
)
def test_reproduces_real_bills_with_eei(kwh: float, caj_semasa: float) -> None:
    assert domestic_bill(kwh).total == pytest.approx(caj_semasa, abs=0.005)


def test_real_bill_with_late_payment_surcharge() -> None:
    # Real 356 kWh bill (Jul 2026): Caj Semasa RM99.84 includes a RM0.62
    # "Surcaj Lewat Bayar" (late-payment surcharge), which isn't tariff.
    assert domestic_bill(356).total == pytest.approx(99.84 - 0.62, abs=0.005)


@pytest.mark.parametrize(
    ("kwh", "rate"),
    [(1, 0.25), (200, 0.25), (201, 0.245), (400, 0.17), (401, 0.145),
     (1000, 0.005), (1001, 0.0)],
)  # fmt: skip
def test_eei_band_edges(kwh: float, rate: float) -> None:
    assert eei_rate(kwh) == rate


def test_no_eei_above_1000_kwh() -> None:
    assert domestic_bill(1001).eei == 0.0
    assert domestic_bill(1295).eei == 0.0


def test_eei_cuts_bill_below_1000_kwh() -> None:
    bill = domestic_bill(380)
    assert bill.eei == pytest.approx(64.60)  # 380 x 17 sen
    assert bill.total < bill.usage_charges + bill.kwtbb


def test_reproduces_tnb_guide_worked_bill_above_600_kwh() -> None:
    # TNB "Guide to Electricity Tariff", worked 625 kWh domestic bill: EEI
    # 7.5 sen split -45.00 (600 kWh untaxed) / -1.88 (25 kWh taxed); KWTBB 3.69.
    # Its two AFA lines (-4.77/-0.20 and -2.98/-0.12) are added back here since
    # they span two rates; without AFA the taxed column is 19.23, so service
    # tax is 1.54 and Caj Semasa is 221.58 + 19.23 + 1.54 + 3.69 = 246.04.
    bill = domestic_bill(625)
    assert bill.eei == pytest.approx(46.88)
    assert bill.kwtbb == pytest.approx(3.69)
    assert bill.service_tax == pytest.approx(1.54)
    assert bill.total == pytest.approx(246.04, abs=0.005)
