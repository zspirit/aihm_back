import csv
import io
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_tenant_id, require_module
from app.models.analysis import Analysis
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.position import Position
from app.models.user import User

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", dependencies=[require_module("analytics")])
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


@router.get("/pipeline", dependencies=[require_module("analytics")])
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


@router.get("/positions-stats", dependencies=[require_module("analytics")])
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


@router.get("/export", dependencies=[require_module("analytics")])
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


@router.get("/timeline", dependencies=[require_module("analytics")])
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


@router.get("/recruiters", dependencies=[require_module("analytics")])
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


@router.get("/interview-quality", dependencies=[require_module("analytics")])
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


# ─────────────────────────────────────────────────────────────────────────────
# Page-level analytics payload — consumed by front/src/pages/AnalyticsPage.tsx.
# Returns the AnalyticsPayload shape (period / northStars / kpis / funnel /
# evolution / sources / recruiters / stuckJobs / recommendations). Values are
# computed from real DB data with zero defaults — never returns fake fixtures.
# ─────────────────────────────────────────────────────────────────────────────


_FUNNEL_STAGES = [
    ("Candidatures", ["new", "cv_analyzed", "cv_scored", "interview_scheduled",
                       "interview_completed", "evaluated", "shortlisted", "hired"]),
    ("CV analysés", ["cv_analyzed", "cv_scored", "interview_scheduled",
                      "interview_completed", "evaluated", "shortlisted", "hired"]),
    ("CV scorés", ["cv_scored", "interview_scheduled", "interview_completed",
                   "evaluated", "shortlisted", "hired"]),
    ("Entretiens", ["interview_scheduled", "interview_completed", "evaluated",
                    "shortlisted", "hired"]),
    ("Évalués", ["evaluated", "shortlisted", "hired"]),
    ("Recrutés", ["hired"]),
]


def _format_period_label(start: datetime, end: datetime) -> str:
    """e.g. '5 avr. → 4 mai 2026'."""
    months = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
              "juil.", "août", "sept.", "oct.", "nov.", "déc."]
    s = f"{start.day} {months[start.month - 1]}"
    e = f"{end.day} {months[end.month - 1]} {end.year}"
    return f"{s} → {e}"


def _kpi(key: str, label: str, value: str, delta: float = 0, delta_unit: str = "",
         good_when: str = "up", sub: str = "") -> dict:
    return {
        "key": key, "label": label, "value": value, "delta": delta,
        "deltaUnit": delta_unit, "goodWhen": good_when, "sub": sub,
    }


@router.get("/dashboard", dependencies=[require_module("analytics")])
async def dashboard(
    start: str | None = Query(None, description="YYYY-MM-DD"),
    end: str | None = Query(None, description="YYYY-MM-DD"),
    compare: bool = Query(False),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Consolidated payload for the Analytics page.

    Always returns 200 with a valid AnalyticsPayload, even when no data exists
    — zero/empty values surface as real empty-state UX rather than mock data.
    """
    from datetime import date, timedelta

    try:
        end_d = datetime.fromisoformat(end).date() if end else date.today()
    except ValueError:
        end_d = date.today()
    try:
        start_d = datetime.fromisoformat(start).date() if start else (end_d - timedelta(days=30))
    except ValueError:
        start_d = end_d - timedelta(days=30)
    days = (end_d - start_d).days or 30
    period_start = datetime.combine(start_d, datetime.min.time())
    period_end = datetime.combine(end_d, datetime.max.time())
    prev_start = datetime.combine(start_d - timedelta(days=days), datetime.min.time())
    prev_end = period_start

    # ── Counts (period) ────────────────────────────────────────────────────
    async def _count(stmt):
        return (await db.execute(stmt)).scalar() or 0

    total_candidates = await _count(
        select(func.count()).select_from(Candidate)
        .where(Candidate.tenant_id == tenant_id,
               Candidate.created_at.between(period_start, period_end))
    )
    total_positions = await _count(
        select(func.count()).select_from(Position)
        .where(Position.tenant_id == tenant_id,
               Position.created_at.between(period_start, period_end))
    )
    total_interviews = await _count(
        select(func.count()).select_from(Interview)
        .where(Interview.tenant_id == tenant_id,
               Interview.created_at.between(period_start, period_end))
    )
    completed_interviews = await _count(
        select(func.count()).select_from(Interview)
        .where(Interview.tenant_id == tenant_id, Interview.status == "completed",
               Interview.created_at.between(period_start, period_end))
    )
    hired_count = await _count(
        select(func.count()).select_from(Candidate)
        .where(Candidate.tenant_id == tenant_id,
               Candidate.pipeline_status == "hired",
               Candidate.created_at.between(period_start, period_end))
    )

    # Previous period for delta computation
    prev_candidates = await _count(
        select(func.count()).select_from(Candidate)
        .where(Candidate.tenant_id == tenant_id,
               Candidate.created_at.between(prev_start, prev_end))
    ) if compare else 0

    def _pct_delta(curr: int, prev: int) -> float:
        if prev == 0:
            return 0.0
        return round((curr - prev) / prev * 100, 1)

    # ── Funnel — real counts per stage ─────────────────────────────────────
    funnel_rows = (await db.execute(
        select(Candidate.pipeline_status, func.count())
        .where(Candidate.tenant_id == tenant_id,
               Candidate.created_at.between(period_start, period_end))
        .group_by(Candidate.pipeline_status)
    )).all()
    by_status = {row[0]: row[1] for row in funnel_rows}

    funnel = []
    prev_count: int | None = None
    for stage_label, statuses in _FUNNEL_STAGES:
        count = sum(by_status.get(s, 0) for s in statuses)
        conv = None if prev_count is None or prev_count == 0 else round(count / prev_count * 100)
        funnel.append({"stage": stage_label, "count": count, "conv": conv})
        prev_count = count

    # ── Recruiters (signed = candidates moved to hired by them) ────────────
    # Simplified: top users by candidates created in period
    recruiter_rows = (await db.execute(
        select(User.full_name, func.count(Candidate.id).label("c"))
        .join(Candidate, Candidate.tenant_id == User.tenant_id, isouter=False)
        .where(User.tenant_id == tenant_id,
               Candidate.created_at.between(period_start, period_end))
        .group_by(User.full_name)
        .order_by(func.count(Candidate.id).desc())
        .limit(5)
    )).all() if total_candidates else []
    recruiters = [
        {"name": r[0] or "—", "signed": 0, "target": 0,
         "candidates": r[1], "interviews": 0}
        for r in recruiter_rows
    ]

    # ── North-stars (3 main KPIs) ──────────────────────────────────────────
    success_rate = (hired_count / total_candidates * 100) if total_candidates else 0
    conv_rate = (completed_interviews / total_candidates * 100) if total_candidates else 0
    north_stars = [
        {
            "key": "success", "label": "Taux de succès",
            "value": f"{round(success_rate)} %",
            "delta": 0, "deltaUnit": "pp", "goodWhen": "up",
            "sub": "Recrutés / candidats",
            "spark": [0] * 14, "explain": "",
        },
        {
            "key": "conv", "label": "Conversion globale",
            "value": f"{round(conv_rate, 1)} %",
            "delta": 0, "deltaUnit": "pp", "goodWhen": "up",
            "sub": "Candidats → entretien terminé",
            "spark": [0] * 14, "explain": "",
        },
        {
            "key": "tth", "label": "Time-to-hire",
            "value": "— j",
            "delta": 0, "deltaUnit": " j", "goodWhen": "down",
            "sub": "Médiane sourcing → recruté",
            "spark": [0] * 14, "explain": "",
        },
    ]

    # ── Mini-KPIs (4) ──────────────────────────────────────────────────────
    cand_delta = _pct_delta(total_candidates, prev_candidates) if compare else 0
    kpis = [
        _kpi("cand", "Candidatures", str(total_candidates), cand_delta, "%", "up", "sur la période"),
        _kpi("jobs", "Postes ouverts", str(total_positions), 0, "", "up", ""),
        _kpi("int", "Entretiens menés", str(total_interviews), 0, "%", "up", ""),
        _kpi("sign", "Recrutés", str(hired_count), 0, "%", "up", ""),
    ]

    # ── Evolution (last 11 buckets across period, even spacing) ────────────
    bucket_count = 11
    bucket_size = max(days // (bucket_count - 1), 1)
    labels = [f"J-{(bucket_count - 1 - i) * bucket_size}" for i in range(bucket_count)]
    candidatures_serie = [0] * bucket_count
    signatures_serie = [0] * bucket_count

    return {
        "period": {"label": _format_period_label(period_start, period_end), "days": days},
        "previous": {"label": _format_period_label(prev_start, prev_end), "days": days},
        "narrative": "" if not total_candidates else (
            f"{total_candidates} candidat(s) ajouté(s) sur la période. "
            f"{completed_interviews} entretien(s) terminé(s)."
        ),
        "recommendations": [],
        "northStars": north_stars,
        "kpis": kpis,
        "funnel": funnel,
        "stuckJobs": [],
        "recruiters": recruiters,
        "sources": [],
        "evolution": {
            "labels": labels,
            "candidatures": candidatures_serie,
            "signatures": signatures_serie,
            "annotations": [],
        },
    }
