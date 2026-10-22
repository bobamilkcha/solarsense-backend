"""Pure feasibility maths (no DB, no network)."""

import pytest
from app.modules.reports import feasibility as fz

FLAT_IRR = dict.fromkeys(range(1, 13), 150.0)  # kWh/m^2 per month


def _flat_rate(kwh: float) -> float:
    return kwh * 0.5


def _run(**overrides) -> fz.FeasibilityResult:
    kwargs = {
        "monthly_kwh": 1000.0,
        "irradiation": FLAT_IRR,
        "shading_factor": 1.0,
        "bill_for_kwh": _flat_rate,
        "system_kwp": 5.0,
        "a": fz.Assumptions(),
    }
    kwargs.update(overrides)
    return fz.evaluate(**kwargs)


def test_production_is_kwp_times_irradiation_times_pr_and_shading() -> None:
    result = _run(shading_factor=0.5)

    # 5 kWp * 150 kWh/m^2 * 0.8 PR * 0.5 shading
    assert result.months[0].production_kwh == pytest.approx(300.0)


def test_self_consumption_and_export_split() -> None:
    m = _run().months[0]  # 600 kWh produced

    assert m.self_consumed_kwh == pytest.approx(360.0)
    assert m.exported_kwh == pytest.approx(240.0)


def test_export_credit_reduces_bill_but_not_below_zero() -> None:
    no_credit = _run().months[0]
    with_credit = _run(a=fz.Assumptions(export_rate=0.2)).months[0]
    huge = _run(system_kwp=100.0, a=fz.Assumptions(export_rate=1.0)).months[0]

    assert with_credit.bill_after_rm == pytest.approx(no_credit.bill_after_rm - 240 * 0.2)
    assert huge.bill_after_rm == 0.0


def test_self_consumption_capped_at_usage() -> None:
    m = _run(system_kwp=100.0).months[0]
    consumption = 1000.0 * 31 / (365.25 / 12)

    assert m.self_consumed_kwh == pytest.approx(consumption)


def test_payback_and_lifetime() -> None:
    a = fz.Assumptions(cost_per_kwp=4000.0, degradation_per_year=0.0, lifetime_years=25)
    result = _run(a=a)

    assert result.system_cost_rm == pytest.approx(20000.0)
    assert result.payback_years == pytest.approx(20000.0 / result.annual_savings_rm)
    assert fz.lifetime_net_savings(result, a) == pytest.approx(
        25 * result.annual_savings_rm - 20000.0
    )


def test_no_savings_means_no_payback() -> None:
    assert _run(a=fz.Assumptions(self_consumption_ratio=0.0)).payback_years is None


def test_recommend_kwp_covers_annual_usage_in_whole_panels() -> None:
    a = fz.Assumptions(panel_wp=500.0)
    # yield = 1800 * 0.8 = 1440 kWh/kWp/yr; 1000*12/1440 = 8.33 kWp -> 16 panels
    assert fz.recommend_kwp(1000.0, FLAT_IRR, 1.0, a) == pytest.approx(8.0)


def test_recommend_kwp_minimum_one_panel() -> None:
    assert fz.recommend_kwp(1.0, FLAT_IRR, 1.0, fz.Assumptions()) == pytest.approx(0.55)
