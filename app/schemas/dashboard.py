"""Pydantic schemas for the Dashboard endpoints.

All endpoints are tenant-scoped and accept period/enterprise filters.  Each
KPI block carries a sparkline (N data points over the current period) and a
delta computed against the previous window of equal length.
"""

from datetime import datetime

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# Overview (KPI strip)
# ─────────────────────────────────────────────────────────────────────────────
class KPIVolumeBlock(BaseModel):
    value: int
    delta_pct: float
    sparkline: list[int] = Field(default_factory=list)


class KPIQualityBlock(BaseModel):
    value: float
    delta_pct: float
    sparkline: list[float] = Field(default_factory=list)


class KPIVelocityBlock(BaseModel):
    value: float  # median days
    delta_days: float
    sparkline: list[float] = Field(default_factory=list)


class KPIEfficiencyBlock(BaseModel):
    value: float  # % (0..100)
    delta_pts: float
    sparkline: list[float] = Field(default_factory=list)


class PeriodRange(BaseModel):
    # Pydantic field name can't be "from" (reserved).  We alias to "from" on
    # both input and output so the JSON payload still says {"from": "..."}.
    from_: datetime = Field(alias="from", serialization_alias="from")
    to: datetime
    compare_from: datetime | None = None
    compare_to: datetime | None = None

    model_config = {"populate_by_name": True}


class DashboardOverviewResponse(BaseModel):
    volume: KPIVolumeBlock
    quality: KPIQualityBlock
    velocity_days: KPIVelocityBlock
    efficiency_pct: KPIEfficiencyBlock
    period: PeriodRange


# ─────────────────────────────────────────────────────────────────────────────
# Funnel
# ─────────────────────────────────────────────────────────────────────────────
class FunnelStage(BaseModel):
    key: str
    label: str
    count: int
    drop_pct_from_prev: float | None = None


class DashboardFunnelResponse(BaseModel):
    stages: list[FunnelStage]


# ─────────────────────────────────────────────────────────────────────────────
# Timeseries
# ─────────────────────────────────────────────────────────────────────────────
class TimeseriesSeriesMeta(BaseModel):
    key: str
    label: str
    color_hint: str


class TimeseriesPoint(BaseModel):
    date: str
    # extra keys are metric-specific (cvs_received, invited, interviews, ...)
    # We lean on an open dict rather than a rigid schema to stay forward-compat.
    model_config = {"extra": "allow"}


class DashboardTimeseriesResponse(BaseModel):
    metric: str
    series: list[TimeseriesSeriesMeta]
    points: list[dict]


# ─────────────────────────────────────────────────────────────────────────────
# Actions required
# ─────────────────────────────────────────────────────────────────────────────
class ActionRequiredItem(BaseModel):
    id: str
    type: str  # candidat | entretien | poste
    severity: str  # late | urgent | high | normal
    title: str
    subtitle: str | None = None
    age_relative: str
    deeplink: str
    created_at: datetime


class ActionsRequiredResponse(BaseModel):
    total: int
    items: list[ActionRequiredItem]


# ─────────────────────────────────────────────────────────────────────────────
# Todo list
# ─────────────────────────────────────────────────────────────────────────────
class TodoItem(BaseModel):
    id: str
    entity_type: str  # candidate | position | interview | client
    title: str
    subtitle: str | None = None
    urgency: str
    score: float | None = None
    status: str
    status_label: str
    last_activity: datetime | None = None


class TodoResponse(BaseModel):
    items: list[TodoItem]


# ─────────────────────────────────────────────────────────────────────────────
# Brief
# ─────────────────────────────────────────────────────────────────────────────
class DashboardBriefResponse(BaseModel):
    headline: str
    insight: str
    insight_link: str | None = None
    actions_count: int
    generated_at: datetime
