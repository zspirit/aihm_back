from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session, get_db
from app.core.dependencies import get_tenant_id, require_role
from app.models.analysis import Analysis
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.match_score import MatchScore
from app.models.position import Position
from app.models.report import Report
from app.models.user import User
from app.schemas.batch_matching import MatchPositionsRequest as _MatchPositionsRequest
from app.schemas.candidate import CandidateComparisonItem

router = APIRouter(tags=["candidates"])


@router.get("/candidates/{candidate_id}/position-matches")
async def candidate_position_matches(
    candidate_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Find other active positions this candidate could match with, based on skill overlap."""
    result = await db.execute(
        select(Candidate).where(Candidate.id == candidate_id, Candidate.tenant_id == tenant_id)
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    cv_data = candidate.cv_parsed_data or {}
    candidate_skills = [s.lower() for s in cv_data.get("skills", [])]

    if not candidate_skills:
        return {"matches": []}

    positions_result = await db.execute(
        select(Position).where(
            Position.tenant_id == tenant_id,
            Position.status == "active",
            Position.id != candidate.position_id,
        )
    )
    positions = positions_result.scalars().all()

    matches = []
    for pos in positions:
        required_skills = pos.required_skills or []
        if not required_skills:
            continue

        required_lower = []
        for rs in required_skills:
            name = (rs if isinstance(rs, str) else rs.get("name", "")).lower()
            if name:
                required_lower.append(name)

        if not required_lower:
            continue

        matched_count = 0
        for rs in required_lower:
            for cs in candidate_skills:
                if rs in cs or cs in rs:
                    matched_count += 1
                    break

        score = round((matched_count / len(required_lower)) * 100)
        if score > 0:
            matches.append({
                "position_id": str(pos.id),
                "title": pos.title,
                "match_score": score,
                "matched_skills": matched_count,
                "total_required": len(required_lower),
            })

    matches.sort(key=lambda x: x["match_score"], reverse=True)
    return {"matches": matches[:10]}


@router.get(
    "/positions/{position_id}/candidates/compare",
    response_model=list[CandidateComparisonItem],
)
async def compare_candidates(
    position_id: UUID,
    candidate_ids: str = Query(..., description="Comma-separated candidate IDs (2-6)"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Compare multiple candidates side-by-side for the same position."""
    raw_ids = [cid.strip() for cid in candidate_ids.split(",") if cid.strip()]
    if len(raw_ids) < 2 or len(raw_ids) > 6:
        raise HTTPException(
            status_code=400,
            detail="Vous devez fournir entre 2 et 6 identifiants de candidats",
        )

    try:
        parsed_ids = [UUID(cid) for cid in raw_ids]
    except ValueError:
        raise HTTPException(status_code=400, detail="Identifiant de candidat invalide")

    result = await db.execute(
        select(Position).where(Position.id == position_id, Position.tenant_id == tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Poste introuvable")

    result = await db.execute(
        select(Candidate).where(
            Candidate.id.in_(parsed_ids),
            Candidate.tenant_id == tenant_id,
        )
    )
    candidates = {c.id: c for c in result.scalars().all()}

    for cid in parsed_ids:
        if cid not in candidates:
            raise HTTPException(
                status_code=404,
                detail=f"Candidat {cid} introuvable",
            )
        if candidates[cid].position_id != position_id:
            raise HTTPException(
                status_code=400,
                detail=f"Le candidat {cid} n'appartient pas a ce poste",
            )

    interview_subq = (
        select(
            Interview.id,
            Interview.candidate_id,
            Interview.duration_seconds,
            Interview.ended_at,
            Interview.attempt_number,
            func.row_number()
            .over(partition_by=Interview.candidate_id, order_by=Interview.created_at.desc())
            .label("rn"),
        )
        .where(Interview.candidate_id.in_(parsed_ids))
        .subquery()
    )

    latest_interviews_q = select(interview_subq).where(interview_subq.c.rn == 1)
    iv_result = await db.execute(latest_interviews_q)
    interviews = {row.candidate_id: row for row in iv_result.all()}

    interview_ids = [row.id for row in interviews.values()]
    analyses = {}
    if interview_ids:
        analysis_result = await db.execute(
            select(Analysis).where(Analysis.interview_id.in_(interview_ids))
        )
        for a in analysis_result.scalars().all():
            analyses[a.interview_id] = a

    reports = {}
    if interview_ids:
        report_result = await db.execute(
            select(Report).where(Report.interview_id.in_(interview_ids))
        )
        for r in report_result.scalars().all():
            reports[r.interview_id] = r

    items = []
    for cid in parsed_ids:
        c = candidates[cid]
        iv = interviews.get(cid)
        iv_id = iv.id if iv else None

        interview_data = None
        if iv:
            interview_data = {
                "duration_seconds": iv.duration_seconds,
                "ended_at": iv.ended_at.isoformat() if iv.ended_at else None,
                "attempt_number": iv.attempt_number,
            }

        analysis = analyses.get(iv_id) if iv_id else None
        scores = analysis.scores if analysis else None
        skill_scores = analysis.skill_scores if analysis else None

        report = reports.get(iv_id) if iv_id else None
        report_summary = None
        if report and report.content and isinstance(report.content, dict):
            report_summary = report.content.get("summary")

        items.append(
            CandidateComparisonItem(
                id=str(c.id),
                name=c.name,
                email=c.email,
                phone=c.phone,
                cv_score=c.cv_score,
                cv_score_explanation=c.cv_score_explanation,
                cv_parsed_data=c.cv_parsed_data,
                pipeline_status=c.pipeline_status,
                interview=interview_data,
                scores=scores,
                skill_scores=skill_scores,
                report_summary=report_summary,
            )
        )

    return items


@router.post(
    "/candidates/{candidate_id}/match-positions",
    status_code=202,
)
async def match_positions_for_candidate(
    candidate_id: UUID,
    body: _MatchPositionsRequest,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """
    Lancer un matching bidirectionnel depuis une fiche candidat.
    Si position_ids est null, prend tous les postes actifs du tenant.
    Retourne un session_id pour tracker la progression via SSE (/matching/sessions/{id}/events).
    """
    from app.models.match_score import MatchSession
    from app.schemas.batch_matching import MatchSessionResponse

    tenant_id = current_user.tenant_id

    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    if not candidate.cv_parsed_data:
        raise HTTPException(
            status_code=400,
            detail="Le candidat n'a pas de CV analyse. Impossible de lancer le matching.",
        )

    if body.position_ids is not None:
        position_uuids = []
        for pid in body.position_ids:
            try:
                position_uuids.append(UUID(pid))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"position_id invalide: {pid}")

        result = await db.execute(
            select(Position.id).where(
                Position.id.in_(position_uuids),
                Position.tenant_id == tenant_id,
            )
        )
        position_uuids = [row[0] for row in result.all()]
    else:
        result = await db.execute(
            select(Position.id).where(
                Position.tenant_id == tenant_id,
                Position.status == "active",
            )
        )
        position_uuids = [row[0] for row in result.all()]

    if not position_uuids:
        raise HTTPException(
            status_code=400,
            detail="Aucun poste actif trouve pour ce tenant",
        )

    total_pairs = len(position_uuids)

    pairs_to_compute = total_pairs
    if not body.force_recompute:
        result = await db.execute(
            select(MatchScore.position_id).where(
                MatchScore.tenant_id == tenant_id,
                MatchScore.candidate_id == candidate_id,
                MatchScore.position_id.in_(position_uuids),
            )
        )
        cached_positions = {row[0] for row in result.all()}
        pairs_to_compute = len(set(position_uuids) - cached_positions)

    session = MatchSession(
        tenant_id=tenant_id,
        user_id=current_user.id,
        position_ids=[str(pid) for pid in position_uuids],
        candidate_ids=[str(candidate_id)],
        status="pending",
        total_pairs=total_pairs,
        computed_pairs=0,
    )
    db.add(session)
    await db.flush()
    session_id = str(session.id)
    await db.commit()

    import structlog
    structlog.get_logger().info(
        "match_session_created_for_candidate",
        session_id=session_id,
        candidate_id=str(candidate_id),
        positions=len(position_uuids),
        pairs_to_compute=pairs_to_compute,
    )

    celery_available = False
    try:
        from app.workers.matching import compute_match_matrix
        compute_match_matrix.delay(session_id)
        celery_available = True
    except Exception:
        pass

    if not celery_available:
        import asyncio as _asyncio
        from starlette.concurrency import run_in_threadpool as _run_in_threadpool

        _sid = session_id

        async def _process_matching_inline():
            try:
                from app.services.batch_matching import compute_batch_matching
                await _run_in_threadpool(compute_batch_matching, _sid)
            except Exception as _exc:
                import structlog as _structlog
                _structlog.get_logger().error("inline_matching_error", session_id=_sid, error=str(_exc))
                async with async_session() as _sess:
                    from app.models.match_score import MatchSession as _MatchSession
                    _r = await _sess.execute(select(_MatchSession).where(_MatchSession.id == UUID(_sid)))
                    _ms = _r.scalar_one_or_none()
                    if _ms:
                        _ms.status = "failed"
                        await _sess.commit()

        _asyncio.create_task(_process_matching_inline())

    return MatchSessionResponse(
        session_id=session_id,
        total_pairs=total_pairs,
        status="pending",
    )
