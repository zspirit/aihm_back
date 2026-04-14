"""Metrics schemas."""
from pydantic import BaseModel
from uuid import UUID


class PositionMetrics(BaseModel):
    position_id: str
    title: str
    total_applications: int
    total_interviews: int
    total_offers: int
    signed_offers: int
    conversion_rate: float
    interview_rate: float
    average_salary: float | None = None


class EnterpriseMetrics(BaseModel):
    enterprise_id: str
    name: str
    open_positions: int
    total_candidates: int
    total_applications: int
    hired: int
    hire_rate: float


class AnalyticsOverview(BaseModel):
    period_days: int
    total_positions: int
    total_candidates: int
    recent_applications: int
    recent_interviews: int
    recent_offers: int
    recent_hired: int
