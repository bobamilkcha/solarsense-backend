import uuid
from typing import Literal

from pydantic import BaseModel, Field


class AssumptionsParams(BaseModel):
    """Overridable inputs; defaults are typical Malaysian residential values."""

    system_kwp: float | None = Field(
        default=None, gt=0, le=1000, description="Omit to size the system to cover annual usage"
    )
    performance_ratio: float = Field(default=0.80, gt=0, le=1)
    self_consumption_ratio: float = Field(default=0.60, ge=0, le=1)
    export_rate_rm_per_kwh: float = Field(
        default=0.0, ge=0, description="Credit for exported energy; 0 = conservative"
    )
    cost_per_kwp_rm: float = Field(default=4000.0, gt=0)
    panel_wp: float = Field(default=550.0, gt=0)
    afa_rate_rm_per_kwh: float = Field(
        default=0.0, description="TNB fuel adjustment (AFA), changes monthly"
    )


class ConsumptionSummary(BaseModel):
    bills_used: int
    avg_monthly_kwh: float
    tariff_category: str | None
    # domestic_2025 = full TNB tariff rules; flat_effective_rate = RM/kWh from bills
    tariff_model: Literal["domestic_2025", "flat_effective_rate"]
    effective_rate_rm_per_kwh: float | None


class ShadingSummary(BaseModel):
    # "device" = measured vs satellite on complete days; "satellite_only" = no
    # complete device days yet, so no shading adjustment applied.
    source: Literal["device", "satellite_only"]
    complete_days: int
    measured_ratio: float | None
    applied_factor: float  # measured_ratio capped at 1.0


class MonthBreakdown(BaseModel):
    month: int
    production_kwh: float
    self_consumed_kwh: float
    exported_kwh: float
    bill_before_rm: float
    bill_after_rm: float
    savings_rm: float


class FeasibilityReport(BaseModel):
    site_id: uuid.UUID
    consumption: ConsumptionSummary
    shading: ShadingSummary
    system_kwp: float
    panel_count: int
    system_cost_rm: float
    annual_irradiation_kwh_m2: float
    annual_production_kwh: float
    annual_consumption_kwh: float
    solar_coverage_pct: float  # share of annual usage met by self-consumed solar
    avg_monthly_bill_before_rm: float
    avg_monthly_bill_after_rm: float
    annual_savings_rm: float
    payback_years: float | None
    lifetime_net_savings_rm: float
    lifetime_years: int
    assumptions: AssumptionsParams
    months: list[MonthBreakdown]
