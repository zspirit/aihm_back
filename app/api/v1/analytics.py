import csv
import io
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_tenant_id
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.position import Position

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview")
async def overview(
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """KPIs globaux du tenant."""
    positions = await db.execute(
        select(func.count()).select_from(Position).where(Position.tenant_id == tenant_id)
    )
    candidates = await db.execute(
        select(func.count()).select_from(Candidate).where(Candidate.tenant_id == tenant_id)
    )
    interviews = await db.execute(
        select(func.count()).select_from(Interview).where(Interview.tenant_id == tenant_id)
    )
    completed = await db.execute(
        select(func.count())
        .select_from(Interview)
        .where(Interview.tenant_id == tenant_id, Interview.status == "completed")
    )
    avg_score = await db.execute(
        select(func.avg(Candidate.cv_score)).where(
            Candidate.tenant_id == tenant_id, Candidate.cv_score.isnot(None)
        )
    )
    avg_duration = await db.execute(
        select(func.avg(Interview.duration_seconds)).where(
            Interview.tenant_id == tenant_id, Interview.duration_seconds.isnot(None)
        )
    )

    total_interviews = interviews.scalar() or 0
    total_completed = completed.scalar() or 0

    return {
        "total_positions": positions.scalar() or 0,
        "total_candidates": candidates.scalar() or 0,
        "total_interviews": total_interviews,
        "completed_interviews": total_completed,
        "success_rate": round(total_completed / total_interviews * 100) if total_interviews else 0,
        "avg_cv_score": round(avg_score.scalar() or 0, 1),
        "avg_interview_duration_s": round(avg_duration.scalar() or 0),
    }


@router.get("/pipeline")
async def pipeline_breakdown(
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Repartition des candidats par etape du pipeline."""
    result = await db.execute(
        select(Candidate.pipeline_status, func.count())
        .where(Candidate.tenant_id == tenant_id)
        .group_by(Candidate.pipeline_status)
    )
    return {row[0]: row[1] for row in result.all()}


@router.get("/positions-stats")
async def positions_stats(
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Stats par poste : nb candidats, nb interviews, score moyen."""
    result = await db.execute(
        select(
            Position.id,
            Position.title,
            func.count(Candidate.id).label("candidates_count"),
            func.avg(Candidate.cv_score).label("avg_cv_score"),
        )
        .join(Candidate, Candidate.position_id == Position.id, isouter=True)
        .where(Position.tenant_id == tenant_id)
        .group_by(Position.id, Position.title)
        .order_by(func.count(Candidate.id).desc())
        .limit(20)
    )
    return [
        {
            "id": str(row.id),
            "title": row.title,
            "candidates_count": row.candidates_count,
            "avg_cv_score": round(row.avg_cv_score or 0, 1),
        }
        for row in result.all()
    ]


@router.get("/export")
async def export_csv(
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Export all candidates with scores as CSV."""
    result = await db.execute(
        select(
            Candidate.name,
            Candidate.email,
            Candidate.phone,
            Candidate.cv_score,
            Candidate.pipeline_status,
            Candidate.created_at,
            Position.title.label("position"),
        )
        .join(Position, Position.id == Candidate.position_id)
        .where(Candidate.tenant_id == tenant_id)
        .order_by(Candidate.created_at.desc())
    )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Nom", "Email", "Telephone", "Score CV", "Statut", "Poste", "Date"])
    for row in result.all():
        writer.writerow([
            row.name,
            row.email or "",
            row.phone or "",
            row.cv_score if row.cv_score is not None else "",
            row.pipeline_status,
            row.position,
            row.created_at.strftime("%Y-%m-%d %H:%M") if row.created_at else "",
        ])

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=aihm_export.csv"},
    )
