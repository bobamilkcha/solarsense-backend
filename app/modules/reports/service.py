import uuid
from collections.abc import Callable

from app.core.config.app_config import app_config
from app.models import Project, SensorReading, Site, TNBBill
from app.modules.benchmark.client import PVGISError, fetch_monthly_irradiation_averages
from app.modules.benchmark.irradiation import daily_irradiation
from app.modules.readings.exceptions import SiteNotFoundError
from app.modules.readings.irradiance import irradiance_wm2
from app.modules.reports import feasibility as fz
from app.modules.reports.exceptions import IrradiationUnavailableError, NoBillDataError
from app.modules.reports.schemas import (
    AssumptionsParams,
    ConsumptionSummary,
    FeasibilityReport,
    MonthBreakdown,
    ShadingSummary,
)
from app.modules.reports.tariff import domestic_bill
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

AVG_MONTH_DAYS = 365.25 / 12


def _is_domestic(tariff: str | None) -> bool:
    return tariff is not None and any(w in tariff.lower() for w in ("domestik", "domestic"))


class ReportsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def feasibility(
        self, site_id: uuid.UUID, company_id: uuid.UUID | None, params: AssumptionsParams
    ) -> FeasibilityReport:
        site = await self._authorized_site(site_id, company_id)

        consumption, bill_for_kwh = await self._consumption(site_id, params.afa_rate_rm_per_kwh)

        try:
            irradiation = await fetch_monthly_irradiation_averages(
                float(site.location_lat), float(site.location_lng)
            )
        except PVGISError as exc:
            raise IrradiationUnavailableError from exc

        shading = await self._shading(site_id, irradiation)

        a = fz.Assumptions(
            performance_ratio=params.performance_ratio,
            self_consumption_ratio=params.self_consumption_ratio,
            export_rate=params.export_rate_rm_per_kwh,
            cost_per_kwp=params.cost_per_kwp_rm,
            panel_wp=params.panel_wp,
        )
        kwp = params.system_kwp or fz.recommend_kwp(
            consumption.avg_monthly_kwh, irradiation, shading.applied_factor, a
        )
        result = fz.evaluate(
            monthly_kwh=consumption.avg_monthly_kwh,
            irradiation=irradiation,
            shading_factor=shading.applied_factor,
            bill_for_kwh=bill_for_kwh,
            system_kwp=kwp,
            a=a,
        )

        annual_consumption = consumption.avg_monthly_kwh * 12
        self_used = sum(m.self_consumed_kwh for m in result.months)
        return FeasibilityReport(
            site_id=site.id,
            consumption=consumption,
            shading=shading,
            system_kwp=result.system_kwp,
            panel_count=result.panel_count,
            system_cost_rm=result.system_cost_rm,
            annual_irradiation_kwh_m2=sum(irradiation.values()),
            annual_production_kwh=result.annual_production_kwh,
            annual_consumption_kwh=annual_consumption,
            solar_coverage_pct=100 * self_used / annual_consumption if annual_consumption else 0,
            avg_monthly_bill_before_rm=sum(m.bill_before_rm for m in result.months) / 12,
            avg_monthly_bill_after_rm=sum(m.bill_after_rm for m in result.months) / 12,
            annual_savings_rm=result.annual_savings_rm,
            payback_years=result.payback_years,
            lifetime_net_savings_rm=fz.lifetime_net_savings(result, a),
            lifetime_years=a.lifetime_years,
            assumptions=params.model_copy(update={"system_kwp": kwp}),
            months=[
                MonthBreakdown(
                    month=m.month,
                    production_kwh=m.production_kwh,
                    self_consumed_kwh=m.self_consumed_kwh,
                    exported_kwh=m.exported_kwh,
                    bill_before_rm=m.bill_before_rm,
                    bill_after_rm=m.bill_after_rm,
                    savings_rm=m.savings_rm,
                )
                for m in result.months
            ],
        )

    async def _consumption(
        self, site_id: uuid.UUID, afa_rate: float
    ) -> tuple[ConsumptionSummary, Callable[[float], float]]:
        bills = (
            await self.db.scalars(
                select(TNBBill)
                .where(TNBBill.site_id == site_id, TNBBill.kwh_used.is_not(None))
                .order_by(TNBBill.billing_period_end.desc().nulls_last(), TNBBill.created_at.desc())
            )
        ).all()
        if not bills:
            raise NoBillDataError

        monthly: list[float] = []
        for bill in bills:
            kwh = float(bill.kwh_used or 0)
            if bill.billing_period_start and bill.billing_period_end:
                days = (bill.billing_period_end - bill.billing_period_start).days + 1
                kwh = kwh * AVG_MONTH_DAYS / days if days > 0 else kwh
            monthly.append(kwh)
        avg_monthly = sum(monthly) / len(monthly)

        priced = [b for b in bills if b.current_charges is not None and b.kwh_used]
        effective_rate = (
            sum(float(b.current_charges or 0) for b in priced)
            / sum(float(b.kwh_used or 0) for b in priced)
            if priced
            else None
        )

        tariff = bills[0].tariff_category  # most recent bill
        if _is_domestic(tariff):
            model = "domestic_2025"

            def bill_for_kwh(kwh: float) -> float:
                return domestic_bill(kwh, afa_rate).total

        elif effective_rate is not None:
            model = "flat_effective_rate"
            rate = effective_rate

            def bill_for_kwh(kwh: float) -> float:
                return kwh * rate

        else:
            raise NoBillDataError(
                "Non-domestic tariff and no bill charges available to derive a rate from"
            )

        summary = ConsumptionSummary(
            bills_used=len(bills),
            avg_monthly_kwh=avg_monthly,
            tariff_category=tariff,
            tariff_model=model,
            effective_rate_rm_per_kwh=effective_rate,
        )
        return summary, bill_for_kwh

    async def _shading(self, site_id: uuid.UUID, irradiation: dict[int, float]) -> ShadingSummary:
        isc = app_config.REFERENCE_CELL_ISC_A
        rows = (
            await self.db.execute(
                select(SensorReading.device_timestamp, SensorReading.cell_current).where(
                    SensorReading.site_id == site_id
                )
            )
        ).all()
        samples = [(ts, irradiance_wm2(float(current), isc)) for ts, current in rows]

        ratios = []
        for day in daily_irradiation(samples):
            satellite_monthly = irradiation.get(day.day.month)
            if day.is_complete and satellite_monthly:
                satellite_daily = satellite_monthly / fz.DAYS_IN_MONTH[day.day.month]
                ratios.append(day.kwh_m2 / satellite_daily)

        if not ratios:
            return ShadingSummary(
                source="satellite_only", complete_days=0, measured_ratio=None, applied_factor=1.0
            )
        measured = sum(ratios) / len(ratios)
        return ShadingSummary(
            source="device",
            complete_days=len(ratios),
            measured_ratio=measured,
            applied_factor=min(measured, 1.0),
        )

    async def _authorized_site(self, site_id: uuid.UUID, company_id: uuid.UUID | None) -> Site:
        site = await self.db.get(Site, site_id)
        if site is None:
            raise SiteNotFoundError

        if company_id is not None:
            project = await self.db.get(Project, site.project_id)
            if project is None or project.company_id != company_id:
                # Site exists, just not in the caller's company — 404, not 403.
                raise SiteNotFoundError

        return site
