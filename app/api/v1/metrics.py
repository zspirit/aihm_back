"""Analytics and metrics endpoints (Phase 3)."""
from uuid import UUID
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from fastapi import APIRouter, Depends, HTTPException, Query
from decimal import Decimal

from app.core.dependencies import get_db, get_current_user
from app.models import (
    User,
    Position,
    Candidate,
    Application,
    Interview,
    Offer,
    Enterprise,
)
from app.schemas.metrics import (
    PositionMetrics,
    EnterpriseMetrics,
    AnalyticsOverview,
)

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/positions/{position_id}", response_model=PositionMetrics)
async def get_position_metrics(
    position_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get detailed metrics for a position."""
    position = await db.get(Position, position_id)
    if not position or position.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Position not found")

    # Count applications
    applications = await db.execute(
        select(func.count(Application.id)).where(
            Application.position_id == position_id
        )
    )
    total_applications = applications.scalar() or 0

    # Count interviews
    interviews = await db.execute(
        select(func.count(Interview.id)).where(
            and_(
                Application.position_id == position_id,
                Interview.application_id == Application.id,
            )
        )
    )
    total_interviews = interviews.scalar() or 0

    # Count offers
    offers = await db.execute(
        select(func.count(Offer.id)).where(
            and_(
                Application.position_id == position_id,
                Offer.application_id == Application.id,
            )
        )
    )
    total_offers = offers.scalar() or 0

    # Count signed offers
    signed_offers = await db.execute(
        select(func.count(Offer.id)).where(
            and_(
                Application.position_id == position_id,
                Offer.application_id == Application.id,
                Offer.status == "signed",
            )
        )
    )
    total_signed = signed_offers.scalar() or 0

    # Average salary from offers
    avg_salary = await db.execute(
        select(func.avg(Offer.salary_min)).where(
            and_(
                Application.position_id == position_id,
                Offer.application_id == Application.id,
                Offer.salary_min.isnot(None),
            )
        )
    )
    avg_salary_value = avg_salary.scalar()

    conversion_rate = (
        (total_signed / total_applications * 100)
        if total_applications > 0
        else 0
    )
    interview_rate = (
        (total_interviews / total_applications * 100)
        if total_applications > 0
        else 0
    )

    return {
        "position_id": str(position_id),
        "title": position.title,
        "total_applications": total_applications,
        "total_interviews": total_interviews,
        "total_offers": total_offers,
        "signed_offers": total_signed,
        "conversion_rate": round(conversion_rate, 2),
        "interview_rate": round(interview_rate, 2),
        "average_salary": float(avg_salary_value) if avg_salary_value else None,
    }


@router.get("/enterprises/{enterprise_id}", response_model=EnterpriseMetrics)
async def get_enterprise_metrics(
    enterprise_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get detailed metrics for an enterprise."""
    enterprise = await db.get(Enterprise, enterprise_id)
    if not enterprise or enterprise.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    # Count open positions
    open_positions = await db.execute(
        select(func.count(Position.id)).where(
            and_(
                Position.enterprise_id == enterprise_id,
                Position.status == "open",
            )
        )
    )
    total_open = open_positions.scalar() or 0

    # Count total candidates
    total_candidates = await db.execute(
        select(func.count(Candidate.id)).where(
            Candidate.tenant_id == current_user.tenant_id
        )
    )
    candidate_count = total_candidates.scalar() or 0

    # Count applications across enterprise positions
    applications = await db.execute(
        select(func.count(Application.id)).where(
            Position.enterprise_id == enterprise_id,
            Application.position_id == Position.id,
        )
    )
    app_count = applications.scalar() or 0

    # Count signed offers across enterprise
    signed = await db.execute(
        select(func.count(Offer.id)).where(
            and_(
                Position.enterprise_id == enterprise_id,
                Application.position_id == Position.id,
                Offer.application_id == Application.id,
                Offer.status == "signed",
            )
        )
    )
    signed_count = signed.scalar() or 0

    return {
        "enterprise_id": str(enterprise_id),
        "name": enterprise.name,
        "open_positions": total_open,
        "total_candidates": candidate_count,
        "total_applications": app_count,
        "hired": signed_count,
        "hire_rate": (
            (signed_count / app_count * 100) if app_count > 0 else 0
        ),
    }


@router.get("/analytics/overview", response_model=AnalyticsOverview)
async def get_analytics_overview(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get high-level analytics overview for the tenant."""
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

    # Total positions
    positions = await db.execute(
        select(func.count(Position.id)).where(
            Position.tenant_id == current_user.tenant_id
        )
    )
    total_positions = positions.scalar() or 0

    # Total candidates
    candidates = await db.execute(
        select(func.count(Candidate.id)).where(
            Candidate.tenant_id == current_user.tenant_id
        )
    )
    total_candidates = candidates.scalar() or 0

    # Applications in period
    applications = await db.execute(
        select(func.count(Application.id)).where(
            and_(
                Application.tenant_id == current_user.tenant_id,
                Application.created_at >= cutoff_date,
            )
        )
    )
    recent_applications = applications.scalar() or 0

    # Interviews in period
    interviews = await db.execute(
        select(func.count(Interview.id)).where(
            and_(
                Interview.tenant_id == current_user.tenant_id,
                Interview.created_at >= cutoff_date,
            )
        )
    )
    recent_interviews = interviews.scalar() or 0

    # Offers in period
    offers = await db.execute(
        select(func.count(Offer.id)).where(
            and_(
                Offer.tenant_id == current_user.tenant_id,
                Offer.created_at >= cutoff_date,
            )
        )
    )
    recent_offers = offers.scalar() or 0

    # Signed in period
    signed = await db.execute(
        select(func.count(Offer.id)).where(
            and_(
                Offer.tenant_id == current_user.tenant_id,
                Offer.status == "signed",
                Offer.signed_at >= cutoff_date,
            )
        )
    )
    recent_signed = signed.scalar() or 0

    return {
        "period_days": days,
        "total_positions": total_positions,
        "total_candidates": total_candidates,
        "recent_applications": recent_applications,
        "recent_interviews": recent_interviews,
        "recent_offers": recent_offers,
        "recent_hired": recent_signed,
    }
