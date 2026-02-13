import csv
import io
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_tenant_id
from app.models.analysis import Analysis
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.position import Position
from app.models.user import User

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview")
async def overview(
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """KPIs globaux du tenant."""
    positions_query = select(func.count()).select_from(Position).where(Position.tenant_id == tenant_id)
    if date_from:
        positions_query = positions_query.where(Position.created_at >= date_from)
    if date_to:
        positions_query = positions_query.where(Position.created_at <= date_to)
    positions = await db.execute(positions_query)

    candidates_query = select(func.count()).select_from(Candidate).where(Candidate.tenant_id == tenant_id)
    if date_from:
        candidates_query = candidates_query.where(Candidate.created_at >= date_from)
    if date_to:
        candidates_query = candidates_query.where(Candidate.created_at <= date_to)
    candidates = await db.execute(candidates_query)

    interviews_query = select(func.count()).select_from(Interview).where(Interview.tenant_id == tenant_id)
    if date_from:
        interviews_query = interviews_query.where(Interview.created_at >= date_from)
    if date_to:
        interviews_query = interviews_query.where(Interview.created_at <= date_to)
    interviews = await db.execute(interviews_query)

    completed_query = (
        select(func.count())
        .select_from(Interview)
        .where(Interview.tenant_id == tenant_id, Interview.status == "completed")
    )
    if date_from:
        completed_query = completed_query.where(Interview.created_at >= date_from)
    if date_to:
        completed_query = completed_query.where(Interview.created_at <= date_to)
    completed = await db.execute(completed_query)

    avg_score_query = select(func.avg(Candidate.cv_score)).where(
        Candidate.tenant_id == tenant_id, Candidate.cv_score.isnot(None)
    )
    if date_from:
        avg_score_query = avg_score_query.where(Candidate.created_at >= date_from)
    if date_to:
        avg_score_query = avg_score_query.where(Candidate.created_at <= date_to)
    avg_score = await db.execute(avg_score_query)

    avg_duration_query = select(func.avg(Interview.duration_seconds)).where(
        Interview.tenant_id == tenant_id, Interview.duration_seconds.isnot(None)
    )
    if date_from:
        avg_duration_query = avg_duration_query.where(Interview.created_at >= date_from)
    if date_to:
        avg_duration_query = avg_duration_query.where(Interview.created_at <= date_to)
    avg_duration = await db.execute(avg_duration_query)

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
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Repartition des candidats par etape du pipeline."""
    query = (
        select(Candidate.pipeline_status, func.count())
        .where(Candidate.tenant_id == tenant_id)
        .group_by(Candidate.pipeline_status)
    )
    if date_from:
        query = query.where(Candidate.created_at >= date_from)
    if date_to:
        query = query.where(Candidate.created_at <= date_to)
    result = await db.execute(query)
    return {row[0]: row[1] for row in result.all()}


@router.get("/positions-stats")
async def positions_stats(
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Stats par poste : nb candidats, nb interviews, score moyen."""
    query = (
        select(
            Position.id,
            Position.title,
            func.count(Candidate.id).label("candidates_count"),
            func.avg(Candidate.cv_score).label("avg_cv_score"),
        )
        .join(Candidate, Candidate.position_id == Position.id, isouter=True)
        .where(Position.tenant_id == tenant_id)
    )
    if date_from:
        query = query.where(Candidate.created_at >= date_from)
    if date_to:
        query = query.where(Candidate.created_at <= date_to)
    query = (
        query.group_by(Position.id, Position.title)
        .order_by(func.count(Candidate.id).desc())
        .limit(20)
    )
    result = await db.execute(query)
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
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Export all candidates with scores as CSV."""
    query = (
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
    )
    if date_from:
        query = query.where(Candidate.created_at >= date_from)
    if date_to:
        query = query.where(Candidate.created_at <= date_to)
    query = query.order_by(Candidate.created_at.desc())
    result = await db.execute(query)

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


@router.get("/timeline")
async def timeline(
    period: str = Query("week"),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Timeline des activites par periode (day, week, month)."""
    if period not in ["day", "week", "month"]:
        period = "week"

    interview_query = (
        select(
            func.date_trunc(period, Interview.created_at).label("period"),
            func.count().label("interviews"),
            func.count().filter(Interview.status == "completed").label("completed"),
        )
        .where(Interview.tenant_id == tenant_id)
    )
    if date_from:
        interview_query = interview_query.where(Interview.created_at >= date_from)
    if date_to:
        interview_query = interview_query.where(Interview.created_at <= date_to)
    interview_query = interview_query.group_by("period").order_by("period")
    interview_result = await db.execute(interview_query)

    candidate_query = (
        select(
            func.date_trunc(period, Candidate.created_at).label("period"),
            func.count().label("candidates"),
        )
        .where(Candidate.tenant_id == tenant_id)
    )
    if date_from:
        candidate_query = candidate_query.where(Candidate.created_at >= date_from)
    if date_to:
        candidate_query = candidate_query.where(Candidate.created_at <= date_to)
    candidate_query = candidate_query.group_by("period").order_by("period")
    candidate_result = await db.execute(candidate_query)

    interview_data = {row.period: {"interviews": row.interviews, "completed": row.completed} for row in interview_result.all()}
    candidate_data = {row.period: row.candidates for row in candidate_result.all()}

    all_periods = set(interview_data.keys()) | set(candidate_data.keys())
    timeline_data = []
    for p in sorted(all_periods):
        timeline_data.append({
            "period": p.strftime("%Y-%m-%d") if p else None,
            "candidates": candidate_data.get(p, 0),
            "interviews": interview_data.get(p, {}).get("interviews", 0),
            "completed": interview_data.get(p, {}).get("completed", 0),
        })

    return timeline_data


@router.get("/recruiters")
async def recruiter_stats(
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Stats par recruteur (activites dans AuditLog)."""
    query = (
        select(
            User.id,
            User.full_name,
            User.email,
            User.role,
            func.count(AuditLog.id).label("total_actions"),
            func.count().filter(AuditLog.entity_type == "candidate").label("candidates_added"),
            func.count().filter(AuditLog.entity_type == "interview").label("interviews_scheduled"),
        )
        .join(User, AuditLog.user_id == User.id)
        .where(AuditLog.tenant_id == tenant_id)
    )
    if date_from:
        query = query.where(AuditLog.created_at >= date_from)
    if date_to:
        query = query.where(AuditLog.created_at <= date_to)
    query = (
        query.group_by(User.id, User.full_name, User.email, User.role)
        .order_by(func.count(AuditLog.id).desc())
    )
    result = await db.execute(query)

    return [
        {
            "user_id": str(row.id),
            "name": row.full_name,
            "email": row.email,
            "role": row.role,
            "total_actions": row.total_actions,
            "candidates_added": row.candidates_added,
            "interviews_scheduled": row.interviews_scheduled,
        }
        for row in result.all()
    ]


@router.get("/interview-quality")
async def interview_quality(
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Qualite des interviews : taux de completion, duree moyenne, score moyen."""
    total_query = select(func.count()).select_from(Interview).where(Interview.tenant_id == tenant_id)
    if date_from:
        total_query = total_query.where(Interview.created_at >= date_from)
    if date_to:
        total_query = total_query.where(Interview.created_at <= date_to)
    total_result = await db.execute(total_query)
    total_interviews = total_result.scalar() or 0

    completed_query = (
        select(func.count())
        .select_from(Interview)
        .where(Interview.tenant_id == tenant_id, Interview.status == "completed")
    )
    if date_from:
        completed_query = completed_query.where(Interview.created_at >= date_from)
    if date_to:
        completed_query = completed_query.where(Interview.created_at <= date_to)
    completed_result = await db.execute(completed_query)
    completed = completed_result.scalar() or 0

    failed_query = (
        select(func.count())
        .select_from(Interview)
        .where(Interview.tenant_id == tenant_id, Interview.status == "failed")
    )
    if date_from:
        failed_query = failed_query.where(Interview.created_at >= date_from)
    if date_to:
        failed_query = failed_query.where(Interview.created_at <= date_to)
    failed_result = await db.execute(failed_query)
    failed = failed_result.scalar() or 0

    no_answer_query = (
        select(func.count())
        .select_from(Interview)
        .where(Interview.tenant_id == tenant_id, Interview.status == "no_answer")
    )
    if date_from:
        no_answer_query = no_answer_query.where(Interview.created_at >= date_from)
    if date_to:
        no_answer_query = no_answer_query.where(Interview.created_at <= date_to)
    no_answer_result = await db.execute(no_answer_query)
    no_answer = no_answer_result.scalar() or 0

    avg_duration_query = (
        select(func.avg(Interview.duration_seconds))
        .where(Interview.tenant_id == tenant_id, Interview.status == "completed", Interview.duration_seconds.isnot(None))
    )
    if date_from:
        avg_duration_query = avg_duration_query.where(Interview.created_at >= date_from)
    if date_to:
        avg_duration_query = avg_duration_query.where(Interview.created_at <= date_to)
    avg_duration_result = await db.execute(avg_duration_query)
    avg_duration = avg_duration_result.scalar() or 0

    avg_score_query = (
        select(func.avg(Analysis.scores["global"].astext.cast(Float)))
        .join(Interview, Analysis.interview_id == Interview.id)
        .where(Interview.tenant_id == tenant_id, Analysis.scores["global"].astext.isnot(None))
    )
    if date_from:
        avg_score_query = avg_score_query.where(Interview.created_at >= date_from)
    if date_to:
        avg_score_query = avg_score_query.where(Interview.created_at <= date_to)
    avg_score_result = await db.execute(avg_score_query)
    avg_global_score = avg_score_result.scalar() or 0

    completion_rate = round(completed / total_interviews * 100, 1) if total_interviews else 0
    no_answer_rate = round(no_answer / total_interviews * 100, 1) if total_interviews else 0

    return {
        "total_interviews": total_interviews,
        "completed": completed,
        "failed": failed,
        "no_answer": no_answer,
        "completion_rate": completion_rate,
        "no_answer_rate": no_answer_rate,
        "avg_duration_seconds": round(avg_duration),
        "avg_global_score": round(avg_global_score, 1),
    }
