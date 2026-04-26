from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_tenant_id
from app.models.analysis import Analysis
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.match_score import MatchScore
from app.models.position import Position
from app.schemas.candidate import (
    BenchmarkResponse,
    ScoringHistoryResponse,
    TopPositionsResponse,
)

router = APIRouter(tags=["candidates"])


@router.get("/candidates/{candidate_id}/analytics/benchmark", response_model=BenchmarkResponse)
async def get_candidate_benchmark(
    candidate_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Benchmark the candidate's profile score and skills against the entire tenant pool."""
    candidate_result = await db.execute(
        select(Candidate).where(Candidate.id == candidate_id, Candidate.tenant_id == tenant_id)
    )
    candidate = candidate_result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    total_in_pool = (
        await db.execute(
            select(func.count(Candidate.id)).where(
                Candidate.tenant_id == tenant_id,
                Candidate.profile_score.isnot(None),
            )
        )
    ).scalar() or 0

    profile_score_percentile: float | None = None
    if candidate.profile_score is not None and total_in_pool > 0:
        lower_count = (
            await db.execute(
                select(func.count(Candidate.id)).where(
                    Candidate.tenant_id == tenant_id,
                    Candidate.profile_score < candidate.profile_score,
                    Candidate.profile_score.isnot(None),
                )
            )
        ).scalar() or 0
        profile_score_percentile = round((lower_count / total_in_pool) * 100, 1)

    skill_benchmarks: list[dict] = []
    candidate_skills: list[dict] = []
    if candidate.profile_competencies and isinstance(candidate.profile_competencies, dict):
        candidate_skills = candidate.profile_competencies.get("technical", []) or []

    if candidate_skills:
        all_comps_rows = (
            await db.execute(
                select(Candidate.profile_competencies).where(
                    Candidate.tenant_id == tenant_id,
                    Candidate.profile_competencies.isnot(None),
                    Candidate.id != candidate_id,
                )
            )
        ).scalars().all()

        pool_skill_levels: dict[str, list[float]] = {}
        for comp in all_comps_rows:
            if not isinstance(comp, dict):
                continue
            for skill_entry in comp.get("technical", []) or []:
                if not isinstance(skill_entry, dict):
                    continue
                normalized = (skill_entry.get("normalized") or skill_entry.get("name", "")).lower().strip()
                level = skill_entry.get("level")
                if normalized and level is not None:
                    try:
                        pool_skill_levels.setdefault(normalized, []).append(float(level))
                    except (TypeError, ValueError):
                        pass

        for skill_entry in candidate_skills:
            if not isinstance(skill_entry, dict):
                continue
            name = skill_entry.get("name", "")
            normalized = (skill_entry.get("normalized") or name).lower().strip()
            level = skill_entry.get("level")
            if not normalized or level is None:
                continue
            try:
                cand_level = float(level)
            except (TypeError, ValueError):
                continue

            pool_levels = pool_skill_levels.get(normalized, [])
            total_with_skill = len(pool_levels)
            percentile = None
            if total_with_skill > 0:
                lower = sum(1 for l in pool_levels if l < cand_level)
                percentile = round((lower / total_with_skill) * 100, 1)

            skill_benchmarks.append({
                "skill": name,
                "level": cand_level,
                "percentile": percentile,
                "total_with_skill": total_with_skill,
            })

    return BenchmarkResponse(
        candidate_id=str(candidate_id),
        profile_score=candidate.profile_score,
        profile_score_percentile=profile_score_percentile,
        skill_benchmarks=skill_benchmarks,
        total_candidates_in_pool=total_in_pool,
    )


@router.get("/candidates/{candidate_id}/analytics/top-positions", response_model=TopPositionsResponse)
async def get_candidate_top_positions(
    candidate_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Top 5 most compatible positions for the candidate, based on existing MatchScores."""
    result = await db.execute(
        select(Candidate).where(Candidate.id == candidate_id, Candidate.tenant_id == tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    rows = (
        await db.execute(
            select(MatchScore, Position.title)
            .join(Position, MatchScore.position_id == Position.id)
            .where(
                MatchScore.candidate_id == candidate_id,
                MatchScore.tenant_id == tenant_id,
            )
            .order_by(MatchScore.score.desc())
            .limit(5)
        )
    ).all()

    if not rows:
        return TopPositionsResponse(positions=[], computed=False)

    positions = []
    for ms, pos_title in rows:
        top_reasons: list[str] = []
        if ms.reasons and isinstance(ms.reasons, dict):
            reasons_raw = ms.reasons.get("top_reasons") or ms.reasons.get("reasons") or []
            if isinstance(reasons_raw, list):
                top_reasons = [str(r) for r in reasons_raw[:3]]
        positions.append({
            "position_id": str(ms.position_id),
            "title": pos_title,
            "match_score": ms.score,
            "top_reasons": top_reasons,
        })

    return TopPositionsResponse(positions=positions, computed=True)


@router.get("/candidates/{candidate_id}/analytics/scoring-history", response_model=ScoringHistoryResponse)
async def get_candidate_scoring_history(
    candidate_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Full scoring history: profile score, match scores, and interview analysis scores, sorted ASC."""
    candidate_result = await db.execute(
        select(Candidate).where(Candidate.id == candidate_id, Candidate.tenant_id == tenant_id)
    )
    candidate = candidate_result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    entries: list[dict] = []

    if candidate.profile_score is not None:
        entries.append({
            "date": candidate.created_at.isoformat() if candidate.created_at else None,
            "type": "profile",
            "score": candidate.profile_score,
            "label": "Score profil",
            "position_title": None,
        })

    match_rows = (
        await db.execute(
            select(MatchScore, Position.title)
            .join(Position, MatchScore.position_id == Position.id)
            .where(MatchScore.candidate_id == candidate_id, MatchScore.tenant_id == tenant_id)
            .order_by(MatchScore.computed_at.asc())
        )
    ).all()

    for ms, pos_title in match_rows:
        entries.append({
            "date": ms.computed_at.isoformat() if ms.computed_at else None,
            "type": "match",
            "score": ms.score,
            "label": f"Match — {pos_title}" if pos_title else "Match",
            "position_title": pos_title,
        })

    analysis_rows = (
        await db.execute(
            select(Analysis.scores, Analysis.created_at, Position.title)
            .join(Interview, Analysis.interview_id == Interview.id)
            .outerjoin(Position, Interview.position_id == Position.id)
            .where(
                Interview.candidate_id == candidate_id,
                Analysis.scores.isnot(None),
            )
            .order_by(Analysis.created_at.asc())
        )
    ).all()

    for a_scores, a_created_at, pos_title in analysis_rows:
        if not isinstance(a_scores, dict):
            continue
        overall = a_scores.get("global") or a_scores.get("overall")
        if overall is None:
            continue
        try:
            score_val = float(overall)
        except (TypeError, ValueError):
            continue
        entries.append({
            "date": a_created_at.isoformat() if a_created_at else None,
            "type": "interview",
            "score": score_val,
            "label": f"Entretien — {pos_title}" if pos_title else "Entretien",
            "position_title": pos_title,
        })

    entries.sort(key=lambda e: (e["date"] is None, e["date"] or ""))

    return ScoringHistoryResponse(entries=entries)
