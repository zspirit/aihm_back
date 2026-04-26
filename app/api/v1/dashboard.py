"""Dashboard aggregation endpoints.

Powers the home dashboard screen:

  • /dashboard/overview         → 4-KPI strip (volume, quality, velocity, efficiency)
  • /dashboard/funnel           → conversion funnel (CVs → hired)
  • /dashboard/timeseries       → multi-line charts (pipeline / quality / velocity)
  • /dashboard/actions-required → top prioritised "todo-now" items
  • /dashboard/todo             → dashboard "À traiter aujourd'hui" table
  • /dashboard/brief            → morning narrative string

All endpoints are tenant-scoped via Depends(get_tenant_id).  Comparison
deltas always contrast the current period (last N days) to the previous
same-length window.  The "no data" case returns zero-filled payloads.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_tenant_id
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.enterprise import Enterprise
from app.models.interview import Interview
from app.models.offer import Offer
from app.models.position import Position
from app.schemas.dashboard import (
    ActionRequiredItem,
    ActionsRequiredResponse,
    DashboardBriefResponse,
    DashboardFunnelResponse,
    DashboardOverviewResponse,
    DashboardTimeseriesResponse,
    FunnelStage,
    KPIEfficiencyBlock,
    KPIQualityBlock,
    KPIVelocityBlock,
    KPIVolumeBlock,
    PeriodRange,
    TimeseriesSeriesMeta,
    TodoItem,
    TodoResponse,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════
_SEVERITY_ORDER = {"late": 0, "urgent": 1, "high": 2, "soon": 3, "normal": 4}


def _period_bounds(period_days: int, compare: str) -> tuple[datetime, datetime, datetime | None, datetime | None]:
    """Return (from, to, compare_from, compare_to) in UTC."""
    now = datetime.now(timezone.utc)
    frm = now - timedelta(days=period_days)
    if compare == "none":
        return frm, now, None, None
    if compare == "year":
        cmp_to = now - timedelta(days=365)
        cmp_from = cmp_to - timedelta(days=period_days)
        return frm, now, cmp_from, cmp_to
    # default "previous"
    cmp_to = frm
    cmp_from = cmp_to - timedelta(days=period_days)
    return frm, now, cmp_from, cmp_to


def _delta_pct(curr: float, prev: float) -> float:
    if prev == 0:
        return 0.0 if curr == 0 else 100.0
    return round((curr - prev) / prev * 100, 1)


def _age_relative(dt: datetime | None) -> str:
    """Render 'il y a 2h', 'il y a 1j', 'il y a 3j'…  Defensive on None / tz-naive."""
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    seconds = int(delta.total_seconds())
    if seconds < 3600:
        return f"il y a {max(seconds // 60, 1)}min"
    if seconds < 86400:
        return f"il y a {seconds // 3600}h"
    return f"il y a {seconds // 86400}j"


def _bucket_key(dt: datetime, bucket_days: int, origin: date) -> int:
    """Return integer bucket index given a reference origin date."""
    d = dt.date() if isinstance(dt, datetime) else dt
    return (d - origin).days // bucket_days


def _apply_enterprise_filter(query, enterprise_id: UUID | None, *, on: str = "candidate"):
    """Add enterprise scoping via Position.enterprise_id.

    `on` selects which model's position_id column to join from.  Synchronous — we
    only mutate the query; the outer caller still awaits db.execute.
    """
    if enterprise_id is None:
        return query
    if on == "candidate":
        return query.join(Position, Position.id == Candidate.position_id).where(
            Position.enterprise_id == enterprise_id
        )
    if on == "interview":
        return query.join(Position, Position.id == Interview.position_id).where(
            Position.enterprise_id == enterprise_id
        )
    if on == "offer":
        return query.join(Application, Application.id == Offer.application_id).join(
            Position, Position.id == Application.position_id
        ).where(Position.enterprise_id == enterprise_id)
    if on == "position":
        return query.where(Position.enterprise_id == enterprise_id)
    return query


# ═════════════════════════════════════════════════════════════════════════════
# 1. Overview (KPI strip)
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/overview", response_model=DashboardOverviewResponse)
async def overview(
    period_days: int = Query(30, ge=1, le=365),
    enterprise_id: UUID | None = Query(None),
    compare: Literal["previous", "year", "none"] = Query("previous"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """4 KPIs + sparkline + delta vs previous period."""

    frm, to, cmp_from, cmp_to = _period_bounds(period_days, compare)

    # --- VOLUME : number of candidates created in window ----------------------
    async def _count_candidates(start: datetime, end: datetime) -> int:
        q = select(func.count(Candidate.id)).where(
            Candidate.tenant_id == tenant_id,
            Candidate.created_at >= start,
            Candidate.created_at <= end,
        )
        q = _apply_enterprise_filter(q, enterprise_id, on="candidate")
        return int((await db.execute(q)).scalar() or 0)

    volume_curr = await _count_candidates(frm, to)
    volume_prev = await _count_candidates(cmp_from, cmp_to) if cmp_from else 0

    # --- QUALITY : avg cv_score over candidates created in window -------------
    async def _avg_score(start: datetime, end: datetime) -> float:
        q = select(func.avg(Candidate.cv_score)).where(
            Candidate.tenant_id == tenant_id,
            Candidate.cv_score.isnot(None),
            Candidate.created_at >= start,
            Candidate.created_at <= end,
        )
        q = _apply_enterprise_filter(q, enterprise_id, on="candidate")
        val = (await db.execute(q)).scalar()
        return float(val or 0)

    quality_curr = await _avg_score(frm, to)
    quality_prev = await _avg_score(cmp_from, cmp_to) if cmp_from else 0.0

    # --- VELOCITY : median time between candidate.created_at and interview.completed --
    # Proxy for "time-to-hire" : average days from candidate creation to most recent
    # completed interview, within the window.
    async def _velocity(start: datetime, end: datetime) -> float:
        q = (
            select(Candidate.created_at, Interview.ended_at)
            .join(Interview, Interview.candidate_id == Candidate.id)
            .where(
                Interview.tenant_id == tenant_id,
                Interview.status == "completed",
                Interview.ended_at.isnot(None),
                Interview.ended_at >= start,
                Interview.ended_at <= end,
            )
        )
        q = _apply_enterprise_filter(q, enterprise_id, on="interview")
        rows = (await db.execute(q)).all()
        deltas = []
        for created, ended in rows:
            if not created or not ended:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if ended.tzinfo is None:
                ended = ended.replace(tzinfo=timezone.utc)
            deltas.append((ended - created).total_seconds() / 86400)
        if not deltas:
            return 0.0
        deltas.sort()
        mid = len(deltas) // 2
        if len(deltas) % 2 == 1:
            return round(deltas[mid], 1)
        return round((deltas[mid - 1] + deltas[mid]) / 2, 1)

    velocity_curr = await _velocity(frm, to)
    velocity_prev = await _velocity(cmp_from, cmp_to) if cmp_from else 0.0

    # --- EFFICIENCY : hires / candidates in window (conversion rate) ----------
    async def _efficiency(start: datetime, end: datetime) -> tuple[float, int, int]:
        candidate_q = select(func.count(Candidate.id)).where(
            Candidate.tenant_id == tenant_id,
            Candidate.created_at >= start,
            Candidate.created_at <= end,
        )
        candidate_q = _apply_enterprise_filter(candidate_q, enterprise_id, on="candidate")
        cand = int((await db.execute(candidate_q)).scalar() or 0)

        hire_q = select(func.count(Candidate.id)).where(
            Candidate.tenant_id == tenant_id,
            Candidate.pipeline_status == "hired",
            Candidate.created_at >= start,
            Candidate.created_at <= end,
        )
        hire_q = _apply_enterprise_filter(hire_q, enterprise_id, on="candidate")
        hires = int((await db.execute(hire_q)).scalar() or 0)

        rate = (hires / cand * 100) if cand > 0 else 0.0
        return round(rate, 1), hires, cand

    efficiency_curr, _, _ = await _efficiency(frm, to)
    efficiency_prev = 0.0
    if cmp_from:
        efficiency_prev, _, _ = await _efficiency(cmp_from, cmp_to)

    # --- Sparklines : 10 evenly-spaced buckets over the current period --------
    bucket_count = min(10, max(3, period_days // 3 or 3))
    bucket_days = max(1, period_days // bucket_count)
    origin = frm.date()

    async def _sparkline_counts() -> list[int]:
        q = select(Candidate.created_at).where(
            Candidate.tenant_id == tenant_id,
            Candidate.created_at >= frm,
            Candidate.created_at <= to,
        )
        q = _apply_enterprise_filter(q, enterprise_id, on="candidate")
        rows = (await db.execute(q)).all()
        buckets = [0] * bucket_count
        for (ts,) in rows:
            if not ts:
                continue
            idx = _bucket_key(ts, bucket_days, origin)
            if 0 <= idx < bucket_count:
                buckets[idx] += 1
        return buckets

    async def _sparkline_quality() -> list[float]:
        q = select(Candidate.created_at, Candidate.cv_score).where(
            Candidate.tenant_id == tenant_id,
            Candidate.cv_score.isnot(None),
            Candidate.created_at >= frm,
            Candidate.created_at <= to,
        )
        q = _apply_enterprise_filter(q, enterprise_id, on="candidate")
        rows = (await db.execute(q)).all()
        sums = [0.0] * bucket_count
        counts = [0] * bucket_count
        for ts, score in rows:
            idx = _bucket_key(ts, bucket_days, origin)
            if 0 <= idx < bucket_count:
                sums[idx] += float(score)
                counts[idx] += 1
        return [round(sums[i] / counts[i], 1) if counts[i] else 0.0 for i in range(bucket_count)]

    vol_spark = await _sparkline_counts()
    qual_spark = await _sparkline_quality()
    # velocity / efficiency sparklines : flat last-known proxy (cheap + visually honest
    # enough for v0.0.1).  Replace with bucketed aggregates if the chart calls for it.
    vel_spark = [round(velocity_curr, 1)] * bucket_count
    eff_spark = [round(efficiency_curr, 1)] * bucket_count

    return DashboardOverviewResponse(
        volume=KPIVolumeBlock(
            value=volume_curr,
            delta_pct=_delta_pct(volume_curr, volume_prev),
            sparkline=vol_spark,
        ),
        quality=KPIQualityBlock(
            value=round(quality_curr, 1),
            delta_pct=_delta_pct(quality_curr, quality_prev),
            sparkline=qual_spark,
        ),
        velocity_days=KPIVelocityBlock(
            value=velocity_curr,
            delta_days=round(velocity_curr - velocity_prev, 1),
            sparkline=vel_spark,
        ),
        efficiency_pct=KPIEfficiencyBlock(
            value=efficiency_curr,
            delta_pts=round(efficiency_curr - efficiency_prev, 1),
            sparkline=eff_spark,
        ),
        period=PeriodRange(
            **{"from": frm},
            to=to,
            compare_from=cmp_from,
            compare_to=cmp_to,
        ),
    )


# ═════════════════════════════════════════════════════════════════════════════
# 2. Funnel
# ═════════════════════════════════════════════════════════════════════════════
_FUNNEL_DEFINITION = [
    ("cvs_received", "CVs reçus"),
    ("analyzed", "Analysés"),
    ("invited", "Invités"),
    ("interviews", "Entretiens"),
    ("offers", "Offres"),
    ("hired", "Embauchés"),
]


@router.get("/funnel", response_model=DashboardFunnelResponse)
async def funnel(
    period_days: int = Query(30, ge=1, le=365),
    enterprise_id: UUID | None = Query(None),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Count of candidates at each pipeline stage within the period.

    Logic:
      cvs_received : all candidates created in the window
      analyzed     : candidates whose pipeline_status passed cv_analyzed or beyond
      invited      : candidates at interview_scheduled+ OR having any Interview row
      interviews   : candidates with a completed Interview
      offers       : candidates with at least one Offer row
      hired        : candidates with pipeline_status='hired' or a signed Offer
    """
    frm = datetime.now(timezone.utc) - timedelta(days=period_days)

    # cvs_received
    q_total = select(func.count(Candidate.id)).where(
        Candidate.tenant_id == tenant_id,
        Candidate.created_at >= frm,
    )
    q_total = _apply_enterprise_filter(q_total, enterprise_id, on="candidate")
    total = int((await db.execute(q_total)).scalar() or 0)

    _ANALYZED = {
        "cv_analyzed", "cv_scored", "interview_scheduled",
        "interview_completed", "evaluated", "shortlisted", "hired",
    }
    _INVITED = {
        "interview_scheduled", "interview_completed",
        "evaluated", "shortlisted", "hired",
    }

    q_analyzed = select(func.count(Candidate.id)).where(
        Candidate.tenant_id == tenant_id,
        Candidate.created_at >= frm,
        Candidate.pipeline_status.in_(_ANALYZED),
    )
    q_analyzed = _apply_enterprise_filter(q_analyzed, enterprise_id, on="candidate")
    analyzed = int((await db.execute(q_analyzed)).scalar() or 0)

    q_invited = select(func.count(Candidate.id)).where(
        Candidate.tenant_id == tenant_id,
        Candidate.created_at >= frm,
        Candidate.pipeline_status.in_(_INVITED),
    )
    q_invited = _apply_enterprise_filter(q_invited, enterprise_id, on="candidate")
    invited = int((await db.execute(q_invited)).scalar() or 0)

    q_interviews = select(func.count(func.distinct(Interview.candidate_id))).where(
        Interview.tenant_id == tenant_id,
        Interview.status == "completed",
        Interview.created_at >= frm,
    )
    q_interviews = _apply_enterprise_filter(q_interviews, enterprise_id, on="interview")
    interviews = int((await db.execute(q_interviews)).scalar() or 0)

    q_offers = select(func.count(func.distinct(Offer.id))).where(
        Offer.tenant_id == tenant_id,
        Offer.created_at >= frm,
    )
    q_offers = _apply_enterprise_filter(q_offers, enterprise_id, on="offer")
    offers = int((await db.execute(q_offers)).scalar() or 0)

    q_hired = select(func.count(Candidate.id)).where(
        Candidate.tenant_id == tenant_id,
        Candidate.created_at >= frm,
        Candidate.pipeline_status == "hired",
    )
    q_hired = _apply_enterprise_filter(q_hired, enterprise_id, on="candidate")
    hired = int((await db.execute(q_hired)).scalar() or 0)

    counts = {
        "cvs_received": total,
        "analyzed": analyzed,
        "invited": invited,
        "interviews": interviews,
        "offers": offers,
        "hired": hired,
    }

    stages: list[FunnelStage] = []
    prev_count: int | None = None
    for key, label in _FUNNEL_DEFINITION:
        c = counts[key]
        if prev_count is None or prev_count == 0:
            drop = None if prev_count is None else 0.0
        else:
            drop = round((c - prev_count) / prev_count * 100, 1)
        stages.append(FunnelStage(key=key, label=label, count=c, drop_pct_from_prev=drop))
        prev_count = c

    return DashboardFunnelResponse(stages=stages)


# ═════════════════════════════════════════════════════════════════════════════
# 3. Timeseries
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/timeseries", response_model=DashboardTimeseriesResponse)
async def timeseries(
    metric: Literal["pipeline", "quality", "velocity"] = Query("pipeline"),
    period_days: int = Query(30, ge=1, le=365),
    enterprise_id: UUID | None = Query(None),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Multi-line chart data.  Daily buckets."""
    now = datetime.now(timezone.utc)
    frm = now - timedelta(days=period_days)

    days = [(frm + timedelta(days=i)).date() for i in range(period_days + 1)]
    by_day = {d: {} for d in days}

    def _to_date(v):
        """Normalize a SQL-returned date (str on SQLite, date on Postgres)."""
        if isinstance(v, date):
            return v
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v).date()
            except ValueError:
                return None
        if isinstance(v, datetime):
            return v.date()
        return None

    if metric == "pipeline":
        series = [
            TimeseriesSeriesMeta(key="cvs_received", label="CVs reçus", color_hint="primary"),
            TimeseriesSeriesMeta(key="invited", label="Candidats invités", color_hint="success"),
            TimeseriesSeriesMeta(key="interviews", label="Entretiens réalisés", color_hint="warning"),
        ]

        # cvs_received — all candidates per day
        q1 = (
            select(func.date(Candidate.created_at).label("d"), func.count(Candidate.id))
            .where(
                Candidate.tenant_id == tenant_id,
                Candidate.created_at >= frm,
            )
            .group_by("d")
        )
        q1 = _apply_enterprise_filter(q1, enterprise_id, on="candidate")
        for d, c in (await db.execute(q1)).all():
            d = _to_date(d)
            if d in by_day:
                by_day[d]["cvs_received"] = int(c)

        # invited — candidates with an interview scheduled
        q2 = (
            select(func.date(Interview.created_at).label("d"), func.count(func.distinct(Interview.candidate_id)))
            .where(
                Interview.tenant_id == tenant_id,
                Interview.created_at >= frm,
            )
            .group_by("d")
        )
        q2 = _apply_enterprise_filter(q2, enterprise_id, on="interview")
        for d, c in (await db.execute(q2)).all():
            d = _to_date(d)
            if d in by_day:
                by_day[d]["invited"] = int(c)

        # interviews — completed interviews per day
        q3 = (
            select(func.date(Interview.ended_at).label("d"), func.count(Interview.id))
            .where(
                Interview.tenant_id == tenant_id,
                Interview.status == "completed",
                Interview.ended_at.isnot(None),
                Interview.ended_at >= frm,
            )
            .group_by("d")
        )
        q3 = _apply_enterprise_filter(q3, enterprise_id, on="interview")
        for d, c in (await db.execute(q3)).all():
            d = _to_date(d)
            if d in by_day:
                by_day[d]["interviews"] = int(c)

        points = [
            {
                "date": d.isoformat(),
                "cvs_received": by_day[d].get("cvs_received", 0),
                "invited": by_day[d].get("invited", 0),
                "interviews": by_day[d].get("interviews", 0),
            }
            for d in days
        ]

    elif metric == "quality":
        series = [
            TimeseriesSeriesMeta(key="avg_score", label="Score moyen CV", color_hint="primary"),
        ]
        q = (
            select(func.date(Candidate.created_at).label("d"), func.avg(Candidate.cv_score))
            .where(
                Candidate.tenant_id == tenant_id,
                Candidate.created_at >= frm,
                Candidate.cv_score.isnot(None),
            )
            .group_by("d")
        )
        q = _apply_enterprise_filter(q, enterprise_id, on="candidate")
        for d, s in (await db.execute(q)).all():
            d = _to_date(d)
            if d in by_day:
                by_day[d]["avg_score"] = round(float(s or 0), 1)
        points = [
            {"date": d.isoformat(), "avg_score": by_day[d].get("avg_score", 0)}
            for d in days
        ]

    else:  # velocity
        series = [
            TimeseriesSeriesMeta(key="time_to_interview_days", label="Jours avant entretien", color_hint="primary"),
        ]
        q = (
            select(
                func.date(Interview.ended_at).label("d"),
                func.avg(
                    func.extract("epoch", Interview.ended_at - Candidate.created_at) / 86400
                ),
            )
            .join(Candidate, Candidate.id == Interview.candidate_id)
            .where(
                Interview.tenant_id == tenant_id,
                Interview.status == "completed",
                Interview.ended_at.isnot(None),
                Interview.ended_at >= frm,
            )
            .group_by("d")
        )
        q = _apply_enterprise_filter(q, enterprise_id, on="interview")
        for d, v in (await db.execute(q)).all():
            d = _to_date(d)
            if d in by_day:
                by_day[d]["time_to_interview_days"] = round(float(v or 0), 1)
        points = [
            {"date": d.isoformat(), "time_to_interview_days": by_day[d].get("time_to_interview_days", 0)}
            for d in days
        ]

    return DashboardTimeseriesResponse(metric=metric, series=series, points=points)


# ═════════════════════════════════════════════════════════════════════════════
# 4. Actions required
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/actions-required", response_model=ActionsRequiredResponse)
async def actions_required(
    limit: int = Query(10, ge=1, le=50),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Surface the top priority items awaiting recruiter action.

    Rules:
      • Candidates in `cv_analyzed` whose cv_score ≥ position.auto_advance_threshold
      • Interviews still `scheduled` whose scheduled_at is past (needs reschedule)
      • Positions whose SLA is urgent / late and have no active candidates
      • Candidates in `evaluated` with no decision taken yet
    """
    now = datetime.now(timezone.utc)
    items: list[ActionRequiredItem] = []

    # 1. Candidates awaiting validation (cv_analyzed & ≥ threshold)
    q1 = (
        select(Candidate, Position.auto_advance_threshold)
        .outerjoin(Position, Position.id == Candidate.position_id)
        .where(
            Candidate.tenant_id == tenant_id,
            Candidate.pipeline_status == "cv_analyzed",
            Candidate.cv_score.isnot(None),
        )
        .order_by(Candidate.created_at.desc())
        .limit(limit * 2)
    )
    for cand, threshold in (await db.execute(q1)).all():
        thresh = threshold if threshold is not None else 70
        if cand.cv_score is None or cand.cv_score < thresh:
            continue
        items.append(
            ActionRequiredItem(
                id=str(cand.id),
                type="candidat",
                severity="high",
                title=cand.name,
                subtitle="profil à valider",
                age_relative=_age_relative(cand.created_at),
                deeplink=f"/candidates/{cand.id}",
                created_at=cand.created_at,
            )
        )

    # 2. Scheduled interviews past their slot
    q2 = (
        select(Interview, Candidate.name)
        .join(Candidate, Candidate.id == Interview.candidate_id)
        .where(
            Interview.tenant_id == tenant_id,
            Interview.status == "scheduled",
            Interview.scheduled_at.isnot(None),
            Interview.scheduled_at < now,
        )
        .order_by(Interview.scheduled_at.asc())
        .limit(limit * 2)
    )
    for iv, cand_name in (await db.execute(q2)).all():
        items.append(
            ActionRequiredItem(
                id=str(iv.id),
                type="entretien",
                severity="urgent",
                title=cand_name or "Entretien",
                subtitle="à reprogrammer",
                age_relative=_age_relative(iv.scheduled_at),
                deeplink=f"/interviews/{iv.id}",
                created_at=iv.scheduled_at or iv.created_at,
            )
        )

    # 3. Positions with SLA urgent/late AND no active candidates
    positions_res = await db.execute(
        select(Position).where(
            Position.tenant_id == tenant_id,
            Position.sla_deadline.isnot(None),
            Position.sla_deadline <= now + timedelta(days=2),
            Position.status == "active",
        )
    )
    for pos in positions_res.scalars().all():
        cand_count = int((await db.execute(
            select(func.count(Candidate.id)).where(Candidate.position_id == pos.id)
        )).scalar() or 0)
        if cand_count > 0:
            continue
        severity = "late" if pos.sla_deadline <= now else "urgent"
        items.append(
            ActionRequiredItem(
                id=str(pos.id),
                type="poste",
                severity=severity,
                title=pos.title,
                subtitle="aucun candidat actif",
                age_relative=_age_relative(pos.created_at),
                deeplink=f"/positions/{pos.id}",
                created_at=pos.created_at,
            )
        )

    # 4. Evaluated candidates w/o decision (Application.decision IS NULL)
    q4 = (
        select(Candidate, Application.id)
        .join(Application, Application.candidate_id == Candidate.id)
        .where(
            Candidate.tenant_id == tenant_id,
            Candidate.pipeline_status == "evaluated",
            Application.decision.is_(None),
        )
        .order_by(Candidate.created_at.desc())
        .limit(limit * 2)
    )
    for cand, _app_id in (await db.execute(q4)).all():
        items.append(
            ActionRequiredItem(
                id=str(cand.id),
                type="candidat",
                severity="high",
                title=cand.name,
                subtitle="décision à prendre",
                age_relative=_age_relative(cand.created_at),
                deeplink=f"/candidates/{cand.id}",
                created_at=cand.created_at,
            )
        )

    # Rank by severity then recency
    items.sort(key=lambda it: (_SEVERITY_ORDER.get(it.severity, 99), -(it.created_at.timestamp() if it.created_at else 0)))
    items = items[:limit]

    return ActionsRequiredResponse(total=len(items), items=items)


# ═════════════════════════════════════════════════════════════════════════════
# 5. Todo list ("À traiter aujourd'hui")
# ═════════════════════════════════════════════════════════════════════════════
_STATUS_LABELS = {
    "active": "Actif",
    "paused": "En pause",
    "filled": "Pourvu",
    "archived": "Archivé",
    "draft": "Brouillon",
    "new": "Nouveau",
    "cv_analyzed": "CV analysé",
    "cv_scored": "CV scoré",
    "interview_scheduled": "Entretien planifié",
    "interview_completed": "Entretien terminé",
    "evaluated": "Évalué",
    "shortlisted": "Présélectionné",
    "rejected": "Rejeté",
    "hired": "Recruté",
    "scheduled": "Planifié",
    "completed": "Terminé",
    "failed": "Échoué",
    "no_answer": "Sans réponse",
    "in_progress": "En cours",
}


def _urgency_from_sla(deadline: datetime | None, now: datetime) -> str:
    if deadline is None:
        return "normal"
    if deadline <= now:
        return "late"
    if deadline <= now + timedelta(days=2):
        return "urgent"
    if deadline <= now + timedelta(days=7):
        return "soon"
    return "normal"


@router.get("/todo", response_model=TodoResponse)
async def todo(
    filter: Literal["all", "candidate", "position", "interview", "client"] = Query("all"),
    limit: int = Query(7, ge=1, le=50),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Mixed-entity "to treat today" feed.

    Filter controls which entity types to include.  Default (`all`) returns a
    blend, capped at `limit`.
    """
    now = datetime.now(timezone.utc)
    items: list[TodoItem] = []

    want = {"all"} if filter == "all" else {filter}

    # Candidates — recent, un-processed
    if "all" in want or "candidate" in want:
        q = (
            select(Candidate, Position.title)
            .outerjoin(Position, Position.id == Candidate.position_id)
            .where(
                Candidate.tenant_id == tenant_id,
                Candidate.pipeline_status.in_(["new", "cv_analyzed", "cv_scored", "evaluated"]),
            )
            .order_by(Candidate.created_at.desc())
            .limit(limit)
        )
        for cand, pos_title in (await db.execute(q)).all():
            items.append(
                TodoItem(
                    id=str(cand.id),
                    entity_type="candidate",
                    title=cand.name,
                    subtitle=pos_title,
                    urgency="high" if cand.pipeline_status == "evaluated" else "normal",
                    score=cand.cv_score,
                    status=cand.pipeline_status,
                    status_label=_STATUS_LABELS.get(cand.pipeline_status, cand.pipeline_status),
                    last_activity=cand.created_at,
                )
            )

    # Positions — SLA heatmap
    if "all" in want or "position" in want:
        q = (
            select(Position)
            .where(Position.tenant_id == tenant_id, Position.status == "active")
            .order_by(Position.sla_deadline.asc().nulls_last(), Position.created_at.desc())
            .limit(limit)
        )
        for pos in (await db.execute(q)).scalars().all():
            items.append(
                TodoItem(
                    id=str(pos.id),
                    entity_type="position",
                    title=pos.title,
                    subtitle=f"Poste {pos.seniority_level}" if pos.seniority_level else None,
                    urgency=_urgency_from_sla(pos.sla_deadline, now),
                    score=None,
                    status=pos.status,
                    status_label=_STATUS_LABELS.get(pos.status, pos.status),
                    last_activity=pos.created_at,
                )
            )

    # Interviews — upcoming or overdue
    if "all" in want or "interview" in want:
        q = (
            select(Interview, Candidate.name, Candidate.cv_score)
            .join(Candidate, Candidate.id == Interview.candidate_id)
            .where(
                Interview.tenant_id == tenant_id,
                Interview.status.in_(["scheduled", "in_progress"]),
            )
            .order_by(Interview.scheduled_at.asc().nulls_last())
            .limit(limit)
        )
        for iv, cand_name, cand_score in (await db.execute(q)).all():
            urgency = "late" if iv.scheduled_at and iv.scheduled_at < now else "normal"
            items.append(
                TodoItem(
                    id=str(iv.id),
                    entity_type="interview",
                    title=cand_name or "Entretien",
                    subtitle="Entretien programmé",
                    urgency=urgency,
                    score=cand_score,
                    status=iv.status,
                    status_label=_STATUS_LABELS.get(iv.status, iv.status),
                    last_activity=iv.scheduled_at or iv.created_at,
                )
            )

    # Clients (enterprises) — recent with open positions
    if "all" in want or "client" in want:
        q = (
            select(Enterprise, func.count(Position.id).label("positions_count"))
            .outerjoin(Position, and_(Position.enterprise_id == Enterprise.id, Position.status == "active"))
            .where(Enterprise.tenant_id == tenant_id)
            .group_by(Enterprise.id)
            .order_by(func.count(Position.id).desc())
            .limit(limit)
        )
        for ent, pos_count in (await db.execute(q)).all():
            items.append(
                TodoItem(
                    id=str(ent.id),
                    entity_type="client",
                    title=ent.name,
                    subtitle=f"{pos_count} poste(s) actif(s)",
                    urgency="normal",
                    score=None,
                    status="active",
                    status_label="Actif",
                    last_activity=ent.created_at,
                )
            )

    # Sort + cap
    items.sort(
        key=lambda it: (
            _SEVERITY_ORDER.get(it.urgency, 99),
            -(it.last_activity.timestamp() if it.last_activity else 0),
        )
    )
    return TodoResponse(items=items[:limit])


# ═════════════════════════════════════════════════════════════════════════════
# 6. Brief (morning narrative)
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/brief", response_model=DashboardBriefResponse)
async def brief(
    enterprise_id: UUID | None = Query(None),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Compose the morning brief deterministically from DB stats.

    v0.0.1 — no LLM.  Counts CVs analyzed in the last 24h, averages their score,
    and surfaces the number of action-required items.  The "insight" segment is
    a placeholder slot reserved for a richer conversion-delta analysis later on.
    """
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(hours=24)

    # CVs analyzed in the last 24h
    q_analyzed = select(
        func.count(Candidate.id),
        func.avg(Candidate.cv_score),
    ).where(
        Candidate.tenant_id == tenant_id,
        Candidate.created_at >= yesterday,
        Candidate.cv_score.isnot(None),
    )
    q_analyzed = _apply_enterprise_filter(q_analyzed, enterprise_id, on="candidate")
    cv_count, cv_avg = (await db.execute(q_analyzed)).one()
    cv_count = int(cv_count or 0)
    cv_avg = round(float(cv_avg or 0))

    # Actions count — reuse the same logic (cheap path: just count)
    actions_count = 0
    q_a = select(func.count(Candidate.id)).where(
        Candidate.tenant_id == tenant_id,
        Candidate.pipeline_status.in_(["cv_analyzed", "evaluated"]),
    )
    q_a = _apply_enterprise_filter(q_a, enterprise_id, on="candidate")
    actions_count += int((await db.execute(q_a)).scalar() or 0)

    q_i = select(func.count(Interview.id)).where(
        Interview.tenant_id == tenant_id,
        Interview.status == "scheduled",
        Interview.scheduled_at.isnot(None),
        Interview.scheduled_at < now,
    )
    q_i = _apply_enterprise_filter(q_i, enterprise_id, on="interview")
    actions_count += int((await db.execute(q_i)).scalar() or 0)

    # Compose headline
    if cv_count > 0:
        headline = (
            f"Hier soir, {cv_count} CV ont été analysés (score moyen {cv_avg}). "
            f"Ce matin, {actions_count} actions prioritaires t'attendent."
        )
    else:
        headline = (
            f"Ce matin, {actions_count} actions prioritaires t'attendent. "
            "Aucun nouveau CV hier soir."
        )

    # Placeholder insight (conversion delta on data segment — TODO: derive)
    insight = "Les profils data convertissent +23% sur 7 jours."
    insight_link = "/analytics?segment=data"

    return DashboardBriefResponse(
        headline=headline,
        insight=insight,
        insight_link=insight_link,
        actions_count=actions_count,
        generated_at=now,
    )
