"""Advanced analytics endpoints — Phase 4.3.

Sits next to app/api/v1/analytics.py (which holds the basic dashboards).
Lives in its own router to keep the boundary between "Phase 1 light analytics"
and "Phase 4 recruiting-intelligence" clear in the codebase + OpenAPI doc.

Endpoints:
- GET /analytics/time-to-hire        — median + p90 time from application
                                        creation to first signed offer.
- GET /analytics/source-effectiveness — per-source: total apps, offers
                                        signed, signed-offer rate.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.application import Application
from app.models.offer import Offer
from app.models.user import User

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    """Linear-interpolation percentile. None on empty input."""
    if not sorted_values:
        return None
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    rank = (pct / 100) * (n - 1)
    lo = int(rank)
    hi = min(lo + 1, n - 1)
    frac = rank - lo
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac


# ─── /analytics/time-to-hire ──────────────────────────────────────────────────


class TimeToHireResponse(BaseModel):
    sample_size: int
    median_days: float | None
    p90_days: float | None
    avg_days: float | None
    window_days: int


@router.get("/time-to-hire", response_model=TimeToHireResponse)
async def time_to_hire(
    window_days: int = Query(180, ge=1, le=730),
    position_id: Optional[UUID] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Time elapsed (days) between Application.created_at and the
    associated Offer.signed_at, for offers signed within the window.
    Returns the median + p90 + avg over the sample.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    stmt = (
        select(
            (
                func.extract("epoch", Offer.signed_at)
                - func.extract("epoch", Application.created_at)
            ).label("delta_seconds")
        )
        .join(Application, Offer.application_id == Application.id)
        .where(
            Application.tenant_id == current_user.tenant_id,
            Offer.status == "signed",
            Offer.signed_at.isnot(None),
            Offer.signed_at >= cutoff,
        )
    )
    if position_id is not None:
        stmt = stmt.where(Application.position_id == position_id)

    rows = (await db.execute(stmt)).all()
    # extract('epoch', ts) returns a numeric/Decimal in PostgreSQL — cast to
    # float so the percentile arithmetic doesn't mix Decimal with float.
    seconds = sorted(float(r.delta_seconds) for r in rows if r.delta_seconds is not None)
    days = [s / 86400 for s in seconds]

    return TimeToHireResponse(
        sample_size=len(days),
        median_days=_percentile(days, 50),
        p90_days=_percentile(days, 90),
        avg_days=(sum(days) / len(days)) if days else None,
        window_days=window_days,
    )


# ─── /analytics/source-effectiveness ──────────────────────────────────────────


class SourceStat(BaseModel):
    source: str
    applications: int
    signed_offers: int
    signed_rate: float  # signed_offers / applications, in [0, 1]


class SourceEffectivenessResponse(BaseModel):
    window_days: int
    total_applications: int
    sources: list[SourceStat]


@router.get("/source-effectiveness", response_model=SourceEffectivenessResponse)
async def source_effectiveness(
    window_days: int = Query(180, ge=1, le=730),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """For each application source (direct_apply, referral, matching, ...):
    how many applications and how many ended in a signed offer."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    # signed_offer = there exists an Offer for the application with status='signed'
    signed_offer_subq = (
        select(Offer.application_id)
        .where(Offer.status == "signed")
        .subquery()
    )
    has_signed = case(
        (Application.id.in_(select(signed_offer_subq.c.application_id)), 1),
        else_=0,
    )

    stmt = (
        select(
            Application.source.label("source"),
            func.count().label("applications"),
            func.sum(has_signed).label("signed_offers"),
        )
        .where(
            Application.tenant_id == current_user.tenant_id,
            Application.created_at >= cutoff,
        )
        .group_by(Application.source)
    )
    rows = (await db.execute(stmt)).all()

    sources = []
    total = 0
    for row in rows:
        apps = int(row.applications)
        signed = int(row.signed_offers or 0)
        total += apps
        sources.append(SourceStat(
            source=row.source if row.source else "(unknown)",
            applications=apps,
            signed_offers=signed,
            signed_rate=(signed / apps) if apps else 0.0,
        ))
    sources.sort(key=lambda s: s.applications, reverse=True)

    return SourceEffectivenessResponse(
        window_days=window_days,
        total_applications=total,
        sources=sources,
    )
