import asyncio
import csv
import io
import json
import os
import secrets
from typing import List
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import async_session, get_db
from app.core.dependencies import check_free_tier_limit, get_tenant_id, require_role
from app.models.candidate import Candidate
from app.models.consent import Consent
from app.models.interview import Interview
from app.models.position import Position
from app.models.user import User
from app.schemas.bulk_import import BulkActionRequest, BulkActionResponse, BulkActionResult
from app.schemas.batch_matching import MatchPositionsRequest as _MatchPositionsRequest
from app.models.analysis import Analysis
from app.models.report import Report
from app.models.transcription import Transcription
from app.models.match_score import MatchScore
from app.schemas.candidate import (
    BenchmarkResponse,
    CandidateComparisonItem,
    CandidateGlobalListResponse,
    CandidateInterviewResponse,
    CandidateListResponse,
    CandidateResponse,
    CandidateUpdate,
    InterviewStatsResponse,
    PaginatedCandidates,
    PaginatedCandidatesGlobal,
    ScoringHistoryResponse,
    TopPositionsResponse,
)
from app.services.audit import log_action
from app.services.storage import upload_file

MAX_CV_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_CV_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
ALLOWED_CV_EXTENSIONS = {".pdf", ".doc", ".docx"}

TERMINAL_STATUSES = {"cv_analyzed", "evaluated", "call_done"}

router = APIRouter(tags=["candidates"])
settings = get_settings()


@router.get("/candidates", response_model=PaginatedCandidatesGlobal)
async def list_all_candidates(
    search: str | None = Query(None, description="Search by name or email"),
    status_filter: str | None = Query(None, description="Filter by pipeline status"),
    position_id: str | None = Query(None, description="Filter by position"),
    sort_by: str = Query("created_at", description="Sort field: created_at, cv_score, name"),
    sort_order: str = Query("desc", description="Sort order: asc, desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    unread: bool | None = Query(None, description="Filter unread candidates (viewed_at IS NULL)"),
    recent: bool | None = Query(None, description="Filter recently imported (<24h)"),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """List all candidates across all positions for the tenant."""
    query = (
        select(Candidate, func.count(Interview.id).label("interview_count"), Position.title)
        .outerjoin(Interview, Candidate.id == Interview.candidate_id)
        .outerjoin(Position, Candidate.position_id == Position.id)
        .where(Candidate.tenant_id == tenant_id)
        .group_by(Candidate.id, Position.title)
    )
    count_query = (
        select(func.count())
        .select_from(Candidate)
        .where(Candidate.tenant_id == tenant_id)
    )

    if search:
        search_filter = or_(
            Candidate.name.ilike(f"%{search}%"),
            Candidate.email.ilike(f"%{search}%"),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    if status_filter:
        query = query.where(Candidate.pipeline_status == status_filter)
        count_query = count_query.where(Candidate.pipeline_status == status_filter)

    if position_id:
        query = query.where(Candidate.position_id == position_id)
        count_query = count_query.where(Candidate.position_id == position_id)

    if unread:
        query = query.where(Candidate.viewed_at.is_(None))
        count_query = count_query.where(Candidate.viewed_at.is_(None))

    if recent:
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        query = query.where(Candidate.created_at >= cutoff)
        count_query = count_query.where(Candidate.created_at >= cutoff)

    total = (await db.execute(count_query)).scalar()

    if sort_by == "cv_score":
        order = Candidate.cv_score.desc().nulls_last() if sort_order == "desc" else Candidate.cv_score.asc().nulls_last()
    elif sort_by == "name":
        order = Candidate.name.desc() if sort_order == "desc" else Candidate.name.asc()
    else:
        order = Candidate.created_at.desc() if sort_order == "desc" else Candidate.created_at.asc()
    query = query.order_by(order)

    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    items = [
        CandidateGlobalListResponse(
            id=str(row[0].id),
            name=row[0].name,
            email=row[0].email,
            phone=row[0].phone,
            cv_score=row[0].cv_score,
            profile_score=row[0].profile_score,
            pipeline_status=row[0].pipeline_status,
            interview_count=row[1],
            position_id=str(row[0].position_id) if row[0].position_id else None,
            position_title=row[2] or "Vivier de talents",
            created_at=row[0].created_at,
            viewed_at=row[0].viewed_at,
        )
        for row in result.all()
    ]

    return PaginatedCandidatesGlobal(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/positions/{position_id}/candidates", response_model=PaginatedCandidates)
async def list_candidates(
    position_id: UUID,
    sort_by: str = "cv_score",
    search: str | None = Query(None, description="Search by name or email"),
    status_filter: str | None = Query(None, description="Filter by pipeline status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Position).where(Position.id == position_id, Position.tenant_id == tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Poste introuvable")

    query = (
        select(Candidate, func.count(Interview.id).label("interview_count"))
        .outerjoin(Interview, Candidate.id == Interview.candidate_id)
        .where(
            Candidate.position_id == position_id,
            Candidate.tenant_id == tenant_id,
        )
        .group_by(Candidate.id)
    )
    count_query = (
        select(func.count())
        .select_from(Candidate)
        .where(
            Candidate.position_id == position_id,
            Candidate.tenant_id == tenant_id,
        )
    )

    if search:
        search_filter = or_(
            Candidate.name.ilike(f"%{search}%"),
            Candidate.email.ilike(f"%{search}%"),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    if status_filter:
        query = query.where(Candidate.pipeline_status == status_filter)
        count_query = count_query.where(Candidate.pipeline_status == status_filter)

    total = (await db.execute(count_query)).scalar()

    if sort_by == "cv_score":
        query = query.order_by(Candidate.cv_score.desc().nulls_last())
    else:
        query = query.order_by(Candidate.created_at.desc())

    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    items = [
        CandidateListResponse(
            id=str(row[0].id),
            name=row[0].name,
            email=row[0].email,
            phone=row[0].phone,
            cv_score=row[0].cv_score,
            pipeline_status=row[0].pipeline_status,
            interview_count=row[1],
            created_at=row[0].created_at,
        )
        for row in result.all()
    ]

    return PaginatedCandidates(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/positions/{position_id}/candidates",
    response_model=CandidateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_candidate(
    position_id: UUID,
    name: str = Form(...),
    email: str | None = Form(None),
    phone: str | None = Form(None),
    cv: UploadFile | None = File(None),
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Position).where(
            Position.id == position_id, Position.tenant_id == current_user.tenant_id
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Poste introuvable")

    cv_path = None
    if cv:
        # Validate file extension
        ext = os.path.splitext(cv.filename or "")[1].lower()
        if ext not in ALLOWED_CV_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail="Format de fichier non supporte. Formats acceptes: PDF, DOC, DOCX",
            )

        # Validate file size (read content once)
        contents = await cv.read()
        if len(contents) > MAX_CV_SIZE:
            raise HTTPException(status_code=400, detail="Le fichier ne doit pas depasser 10 MB")
        await cv.seek(0)  # Reset for later processing

        cv_path = await upload_file(
            cv, settings.S3_BUCKET_CVS, f"{current_user.tenant_id}/{position_id}"
        )

    candidate = Candidate(
        tenant_id=current_user.tenant_id,
        position_id=position_id,
        name=name,
        email=email,
        phone=phone,
        cv_file_path=cv_path,
    )
    db.add(candidate)
    await db.flush()

    for consent_type in ["data_processing", "call_recording"]:
        consent = Consent(
            candidate_id=candidate.id,
            token=secrets.token_urlsafe(32),
            type=consent_type,
        )
        db.add(consent)

    if cv_path:
        try:
            from app.workers.cv_processing import process_cv

            process_cv.delay(str(candidate.id))
        except Exception:
            pass  # Celery worker unavailable, CV will be processed later

    return CandidateResponse(
        id=str(candidate.id),
        position_id=str(candidate.position_id),
        name=candidate.name,
        email=candidate.email,
        phone=candidate.phone,
        cv_file_path=candidate.cv_file_path,
        cv_score=candidate.cv_score,
        cv_score_explanation=candidate.cv_score_explanation,
        cv_parsed_data=candidate.cv_parsed_data,
        pipeline_status=candidate.pipeline_status,
        created_at=candidate.created_at,
    )


@router.post(
    "/positions/{position_id}/candidates/batch",
    status_code=status.HTTP_201_CREATED,
)
async def batch_create_candidates(
    position_id: UUID,
    cvs: List[UploadFile] = File(...),
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Position).where(
            Position.id == position_id, Position.tenant_id == current_user.tenant_id
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Poste introuvable")

    created = []
    for cv_file in cvs:
        filename = cv_file.filename or "candidat"

        # Validate file extension
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_CV_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Format de fichier non supporte pour '{filename}'. Formats acceptes: PDF, DOC, DOCX",
            )

        # Validate file size
        contents = await cv_file.read()
        if len(contents) > MAX_CV_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"Le fichier '{filename}' ne doit pas depasser 10 MB",
            )
        await cv_file.seek(0)

        name = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip()
        if not name:
            name = "Candidat"

        cv_path = await upload_file(
            cv_file, settings.S3_BUCKET_CVS, f"{current_user.tenant_id}/{position_id}"
        )

        candidate = Candidate(
            tenant_id=current_user.tenant_id,
            position_id=position_id,
            name=name,
            cv_file_path=cv_path,
        )
        db.add(candidate)
        await db.flush()

        for consent_type in ["data_processing", "call_recording"]:
            consent = Consent(
                candidate_id=candidate.id,
                token=secrets.token_urlsafe(32),
                type=consent_type,
            )
            db.add(consent)

        try:
            from app.workers.cv_processing import process_cv

            process_cv.delay(str(candidate.id))
        except Exception:
            pass  # Celery worker unavailable

        created.append(
            {
                "id": str(candidate.id),
                "name": candidate.name,
                "cv_file_path": candidate.cv_file_path,
            }
        )

    return {"created": len(created), "candidates": created}


@router.get("/positions/{position_id}/candidates/export")
async def export_candidates_csv(
    position_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Position).where(Position.id == position_id, Position.tenant_id == tenant_id)
    )
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status_code=404, detail="Poste introuvable")

    cand_result = await db.execute(
        select(Candidate)
        .where(Candidate.position_id == position_id, Candidate.tenant_id == tenant_id)
        .order_by(Candidate.cv_score.desc().nulls_last())
    )
    candidates = cand_result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Nom", "Email", "Telephone", "Score CV", "Statut", "Date creation"])
    for c in candidates:
        writer.writerow(
            [
                c.name,
                c.email or "",
                c.phone or "",
                round(c.cv_score, 1) if c.cv_score is not None else "",
                c.pipeline_status,
                c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else "",
            ]
        )

    csv_content = output.getvalue()
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="candidats_{position_id}.csv"'},
    )


@router.get("/candidates/unread-count")
async def get_unread_count(
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Return count of candidates not yet viewed (viewed_at IS NULL)."""
    result = await db.execute(
        select(func.count()).select_from(Candidate).where(
            Candidate.tenant_id == tenant_id,
            Candidate.viewed_at.is_(None),
        )
    )
    return {"count": result.scalar() or 0}


@router.get("/candidates/{candidate_id}/cv/download")
async def download_cv(
    candidate_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Telecharge le CV original d'un candidat depuis MinIO."""
    result = await db.execute(
        select(Candidate).where(Candidate.id == candidate_id, Candidate.tenant_id == tenant_id)
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")
    if not candidate.cv_file_path:
        raise HTTPException(status_code=404, detail="Aucun CV disponible pour ce candidat")
    try:
        from app.services.storage import download_file
        parts = candidate.cv_file_path.split("/", 1)
        if len(parts) != 2:
            raise HTTPException(status_code=500, detail="Chemin CV invalide")
        content = await asyncio.get_event_loop().run_in_executor(
            None, download_file, parts[0], parts[1]
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur lors du telechargement: {str(e)}")
    filename = (candidate.cv_parsed_data or {}).get(
        "original_filename",
        f"{candidate.name.replace(' ', '_') if candidate.name else 'cv'}.pdf",
    )
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/candidates/{candidate_id}", response_model=CandidateResponse)
async def get_candidate(
    candidate_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Candidate).where(Candidate.id == candidate_id, Candidate.tenant_id == tenant_id)
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    if not candidate.viewed_at:
        from datetime import datetime, timezone
        candidate.viewed_at = datetime.now(timezone.utc)
        await db.commit()

    from app.models.interview import Interview

    interview_result = await db.execute(
        select(Interview.id)
        .where(Interview.candidate_id == candidate_id)
        .order_by(Interview.created_at.desc())
        .limit(1)
    )
    latest_interview_id = interview_result.scalar_one_or_none()

    return CandidateResponse(
        id=str(candidate.id),
        position_id=str(candidate.position_id) if candidate.position_id else "",
        name=candidate.name,
        email=candidate.email,
        phone=candidate.phone,
        cv_file_path=candidate.cv_file_path,
        cv_score=candidate.cv_score,
        cv_score_explanation=candidate.cv_score_explanation,
        cv_parsed_data=candidate.cv_parsed_data,
        pipeline_status=candidate.pipeline_status,
        interview_id=str(latest_interview_id) if latest_interview_id else None,
        created_at=candidate.created_at,
        viewed_at=candidate.viewed_at,
        profile_score=candidate.profile_score,
        profile_score_explanation=candidate.profile_score_explanation,
        profile_competencies=candidate.profile_competencies,
        profile_suggestions=candidate.profile_suggestions,
        tags=candidate.tags,
        notes=candidate.notes,
    )


@router.get("/candidates/{candidate_id}/interviews", response_model=list[CandidateInterviewResponse])
async def list_candidate_interviews(
    candidate_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """List all interviews for a candidate, enriched with analysis scores and report status."""
    result = await db.execute(
        select(Candidate).where(Candidate.id == candidate_id, Candidate.tenant_id == tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    query = (
        select(Interview, Position.title, Analysis.scores, Analysis.skill_scores, Report.id)
        .outerjoin(Position, Interview.position_id == Position.id)
        .outerjoin(Analysis, Analysis.interview_id == Interview.id)
        .outerjoin(Report, Report.interview_id == Interview.id)
        .where(Interview.candidate_id == candidate_id)
        .order_by(Interview.created_at.desc())
    )
    rows = (await db.execute(query)).all()

    items = []
    for iv, pos_title, analysis_scores, analysis_skill_scores, report_id in rows:
        # Extract overall score from Analysis.scores JSONB
        overall_score = None
        analysis_summary = None
        if analysis_scores and isinstance(analysis_scores, dict):
            overall_score = analysis_scores.get("global") or analysis_scores.get("overall")
            analysis_summary = analysis_scores.get("summary")

        items.append(
            CandidateInterviewResponse(
                id=str(iv.id),
                candidate_id=str(iv.candidate_id),
                position_id=str(iv.position_id) if iv.position_id else None,
                position_title=pos_title,
                status=iv.status,
                scheduled_at=iv.scheduled_at.isoformat() if iv.scheduled_at else None,
                started_at=iv.started_at.isoformat() if iv.started_at else None,
                completed_at=iv.ended_at.isoformat() if iv.ended_at else None,
                duration_seconds=iv.duration_seconds,
                attempt_number=iv.attempt_number,
                analysis_score=overall_score,
                analysis_summary=analysis_summary,
                skill_scores=analysis_skill_scores,
                has_report=report_id is not None,
                report_id=str(report_id) if report_id else None,
                created_at=iv.created_at.isoformat() if iv.created_at else None,
            )
        )
    return items


@router.get("/candidates/{candidate_id}/interviews/stats", response_model=InterviewStatsResponse)
async def get_candidate_interview_stats(
    candidate_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated statistics for all interviews of a candidate."""
    result = await db.execute(
        select(Candidate).where(Candidate.id == candidate_id, Candidate.tenant_id == tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    # Total count and status breakdown
    status_rows = (
        await db.execute(
            select(Interview.status, func.count(Interview.id).label("cnt"))
            .where(Interview.candidate_id == candidate_id)
            .group_by(Interview.status)
        )
    ).all()

    interviews_by_status: dict = {}
    total_interviews = 0
    completed = 0
    for row_status, cnt in status_rows:
        interviews_by_status[row_status] = cnt
        total_interviews += cnt
        if row_status == "completed":
            completed = cnt

    completion_rate = (completed / total_interviews) if total_interviews > 0 else 0.0

    # Aggregated duration from interviews
    duration_result = (
        await db.execute(
            select(func.avg(Interview.duration_seconds))
            .where(Interview.candidate_id == candidate_id, Interview.duration_seconds.isnot(None))
        )
    ).scalar()
    average_duration_seconds = int(duration_result) if duration_result is not None else None

    # Score aggregates from analyses (scores->>'global')
    scores_rows = (
        await db.execute(
            select(Analysis.scores)
            .join(Interview, Analysis.interview_id == Interview.id)
            .where(Interview.candidate_id == candidate_id, Analysis.scores.isnot(None))
        )
    ).scalars().all()

    score_values = []
    for s in scores_rows:
        if isinstance(s, dict):
            val = s.get("global") or s.get("overall")
            if val is not None:
                try:
                    score_values.append(float(val))
                except (TypeError, ValueError):
                    pass

    average_score = (sum(score_values) / len(score_values)) if score_values else None
    best_score = max(score_values) if score_values else None
    worst_score = min(score_values) if score_values else None

    return InterviewStatsResponse(
        total_interviews=total_interviews,
        completed=completed,
        completion_rate=round(completion_rate, 4),
        average_score=round(average_score, 2) if average_score is not None else None,
        average_duration_seconds=average_duration_seconds,
        best_score=round(best_score, 2) if best_score is not None else None,
        worst_score=round(worst_score, 2) if worst_score is not None else None,
        interviews_by_status=interviews_by_status,
    )


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

    # Total candidates in pool with a profile_score
    total_in_pool = (
        await db.execute(
            select(func.count(Candidate.id)).where(
                Candidate.tenant_id == tenant_id,
                Candidate.profile_score.isnot(None),
            )
        )
    ).scalar() or 0

    # Profile score percentile: percentage of candidates with a lower score
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

    # Skill benchmarks: compare candidate's technical skills with pool
    skill_benchmarks: list[dict] = []
    candidate_skills: list[dict] = []
    if candidate.profile_competencies and isinstance(candidate.profile_competencies, dict):
        candidate_skills = candidate.profile_competencies.get("technical", []) or []

    if candidate_skills:
        # Fetch all other candidates' profile_competencies in one query
        all_comps_rows = (
            await db.execute(
                select(Candidate.profile_competencies).where(
                    Candidate.tenant_id == tenant_id,
                    Candidate.profile_competencies.isnot(None),
                    Candidate.id != candidate_id,
                )
            )
        ).scalars().all()

        # Build a skill -> list of levels map across the pool
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

    # 1. Profile score entry
    if candidate.profile_score is not None:
        entries.append({
            "date": candidate.created_at.isoformat() if candidate.created_at else None,
            "type": "profile",
            "score": candidate.profile_score,
            "label": "Score profil",
            "position_title": None,
        })

    # 2. Match scores
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

    # 3. Interview analysis scores
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

    # Sort all entries by date ASC (None dates go last)
    entries.sort(key=lambda e: (e["date"] is None, e["date"] or ""))

    return ScoringHistoryResponse(entries=entries)


@router.post("/candidates/{candidate_id}/grant-consent")
async def grant_consent_admin(
    candidate_id: UUID,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    from datetime import datetime, timezone

    consents_result = await db.execute(select(Consent).where(Consent.candidate_id == candidate_id))
    consents = consents_result.scalars().all()
    for consent in consents:
        if not consent.granted:
            consent.granted = True
            consent.granted_at = datetime.now(timezone.utc)
            consent.channel = "admin"

    candidate.pipeline_status = "consent_given"
    return {"status": "ok", "consents_granted": len(consents)}


@router.post("/candidates/{candidate_id}/reprocess-cv")
async def reprocess_cv(
    candidate_id: UUID,
    position_id: str | None = Query(None, description="Position to score against (optional)"),
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Re-trigger CV analysis for a candidate. If position_id provided, score against that position."""
    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    if not candidate.cv_file_path:
        raise HTTPException(status_code=400, detail="Aucun fichier CV associe a ce candidat")

    celery_ok = False
    try:
        from app.workers.cv_processing import process_cv

        process_cv.delay(str(candidate.id), position_id)
        celery_ok = True
    except Exception:
        pass

    if not celery_ok:
        # Inline fallback — run synchronously in threadpool
        import asyncio
        from starlette.concurrency import run_in_threadpool

        cid = str(candidate.id)
        pid = position_id

        async def _run_inline():
            try:
                from app.workers.cv_processing import process_cv as _pvc
                await run_in_threadpool(_pvc, cid, pid)
            except Exception as exc:
                import structlog
                structlog.get_logger().warning("inline_reprocess_error", candidate_id=cid, error=str(exc))

        asyncio.create_task(_run_inline())

    return {"status": "ok", "message": "Analyse CV relancee"}


@router.delete("/candidates/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_candidate(
    candidate_id: UUID,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    await log_action(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="delete_candidate",
        entity_type="candidate",
        entity_id=str(candidate_id),
        details={"name": candidate.name, "email": candidate.email},
    )

    # Delete related records explicitly (async SQLAlchemy can't lazy-load for ORM cascade)
    interview_ids_result = await db.execute(
        select(Interview.id).where(Interview.candidate_id == candidate_id)
    )
    interview_ids = [row[0] for row in interview_ids_result.all()]

    if interview_ids:
        await db.execute(delete(Report).where(Report.interview_id.in_(interview_ids)))
        await db.execute(delete(Transcription).where(Transcription.interview_id.in_(interview_ids)))
        await db.execute(delete(Analysis).where(Analysis.interview_id.in_(interview_ids)))
        await db.execute(delete(Interview).where(Interview.candidate_id == candidate_id))

    await db.execute(delete(Consent).where(Consent.candidate_id == candidate_id))
    await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
    await db.commit()


@router.put("/candidates/{candidate_id}", response_model=CandidateResponse)
async def update_candidate(
    candidate_id: UUID,
    body: CandidateUpdate,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    if body.name is not None:
        candidate.name = body.name
    if body.email is not None:
        candidate.email = body.email
    if body.phone is not None:
        candidate.phone = body.phone
    if body.tags is not None:
        candidate.tags = body.tags
    if body.notes is not None:
        candidate.notes = body.notes

    await log_action(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="update_candidate",
        entity_type="candidate",
        entity_id=str(candidate_id),
        details=body.model_dump(exclude_none=True),
    )

    await db.commit()
    await db.refresh(candidate)

    # Fetch latest interview id for the response schema
    interview_result = await db.execute(
        select(Interview.id)
        .where(Interview.candidate_id == candidate_id)
        .order_by(Interview.created_at.desc())
        .limit(1)
    )
    latest_interview_id = interview_result.scalar_one_or_none()

    return CandidateResponse(
        id=str(candidate.id),
        position_id=str(candidate.position_id) if candidate.position_id else "",
        name=candidate.name,
        email=candidate.email,
        phone=candidate.phone,
        cv_file_path=candidate.cv_file_path,
        cv_score=candidate.cv_score,
        cv_score_explanation=candidate.cv_score_explanation,
        cv_parsed_data=candidate.cv_parsed_data,
        pipeline_status=candidate.pipeline_status,
        interview_id=str(latest_interview_id) if latest_interview_id else None,
        created_at=candidate.created_at,
        viewed_at=candidate.viewed_at,
        profile_score=candidate.profile_score,
        profile_score_explanation=candidate.profile_score_explanation,
        profile_competencies=candidate.profile_competencies,
        profile_suggestions=candidate.profile_suggestions,
        tags=candidate.tags,
        notes=candidate.notes,
    )


@router.get("/candidates/{candidate_id}/events")
async def candidate_events(
    candidate_id: UUID,
    request: Request,
    tenant_id: UUID = Depends(get_tenant_id),
):
    async def event_stream():
        last_status = None
        last_score = None
        while True:
            if await request.is_disconnected():
                break
            async with async_session() as db:
                result = await db.execute(
                    select(Candidate).where(
                        Candidate.id == candidate_id, Candidate.tenant_id == tenant_id
                    )
                )
                candidate = result.scalar_one_or_none()
                from app.models.interview import Interview

                iv_result = await db.execute(
                    select(Interview.id)
                    .where(Interview.candidate_id == candidate_id)
                    .order_by(Interview.created_at.desc())
                    .limit(1)
                )
                latest_iv_id = iv_result.scalar_one_or_none()
            if not candidate:
                yield f"event: error\ndata: {json.dumps({'detail': 'Candidat introuvable'})}\n\n"
                break
            status_changed = candidate.pipeline_status != last_status
            score_changed = candidate.cv_score != last_score
            if status_changed or score_changed:
                last_status = candidate.pipeline_status
                last_score = candidate.cv_score
                data = {
                    "pipeline_status": candidate.pipeline_status,
                    "cv_score": candidate.cv_score,
                    "cv_score_explanation": candidate.cv_score_explanation,
                    "cv_parsed_data": candidate.cv_parsed_data,
                    "interview_id": str(latest_iv_id) if latest_iv_id else None,
                }
                yield (
                    f"event: update\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
                )
                if candidate.pipeline_status in TERMINAL_STATUSES:
                    yield (
                        f"event: done\ndata: "
                        f"{json.dumps({'status': candidate.pipeline_status})}\n\n"
                    )
                    break
            await asyncio.sleep(3)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/positions/{position_id}/candidates/bulk-action")
async def bulk_action(
    position_id: UUID,
    body: BulkActionRequest,
    request: Request,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    if len(body.candidate_ids) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 candidats autorises par action")

    if body.action not in ("schedule", "reject", "delete"):
        raise HTTPException(status_code=400, detail="Action non supportee")

    result = await db.execute(
        select(Position).where(
            Position.id == position_id, Position.tenant_id == current_user.tenant_id
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Poste introuvable")

    # Free tier enforcement: check before scheduling interviews
    if body.action == "schedule":
        await check_free_tier_limit(db, current_user.tenant_id)

    results = []
    success_count = 0
    failed_count = 0

    for candidate_id_str in body.candidate_ids:
        try:
            candidate_id = UUID(candidate_id_str)
            cand_result = await db.execute(
                select(Candidate).where(
                    Candidate.id == candidate_id,
                    Candidate.tenant_id == current_user.tenant_id,
                    Candidate.position_id == position_id,
                )
            )
            candidate = cand_result.scalar_one_or_none()
            if not candidate:
                results.append(
                    BulkActionResult(
                        candidate_id=candidate_id_str,
                        status="error",
                        reason="Candidat introuvable",
                    )
                )
                failed_count += 1
                continue

            if body.action == "schedule":
                # Check consent granted
                consent_result = await db.execute(
                    select(Consent).where(
                        Consent.candidate_id == candidate_id,
                        Consent.type == "call_recording",
                        Consent.granted.is_(True),
                    )
                )
                if not consent_result.scalar_one_or_none():
                    results.append(
                        BulkActionResult(
                            candidate_id=candidate_id_str,
                            status="error",
                            reason="Consentement non donne",
                        )
                    )
                    failed_count += 1
                    continue

                # Check phone exists
                if not candidate.phone:
                    results.append(
                        BulkActionResult(
                            candidate_id=candidate_id_str,
                            status="error",
                            reason="Numero de telephone manquant",
                        )
                    )
                    failed_count += 1
                    continue

                # Check max attempts
                attempts = await db.execute(
                    select(Interview).where(Interview.candidate_id == candidate_id)
                )
                attempt_count = len(attempts.scalars().all())
                if attempt_count >= 3:
                    results.append(
                        BulkActionResult(
                            candidate_id=candidate_id_str,
                            status="error",
                            reason="Nombre maximum de tentatives atteint (3)",
                        )
                    )
                    failed_count += 1
                    continue

                # Create interview
                interview = Interview(
                    candidate_id=candidate_id,
                    position_id=position_id,
                    tenant_id=current_user.tenant_id,
                    scheduled_at=None,
                    attempt_number=attempt_count + 1,
                )
                db.add(interview)
                await db.flush()

                candidate.pipeline_status = "call_scheduled"

                # Trigger call
                try:
                    from app.workers.telephony import initiate_call

                    initiate_call.delay(str(interview.id))
                except Exception:
                    pass  # Celery worker unavailable

                results.append(
                    BulkActionResult(
                        candidate_id=candidate_id_str,
                        status="ok",
                        reason=None,
                    )
                )
                success_count += 1

            elif body.action == "reject":
                candidate.pipeline_status = "rejected"
                results.append(
                    BulkActionResult(
                        candidate_id=candidate_id_str,
                        status="ok",
                        reason=None,
                    )
                )
                success_count += 1

            elif body.action == "delete":
                await log_action(
                    db,
                    tenant_id=current_user.tenant_id,
                    user_id=current_user.id,
                    action="bulk_delete_candidate",
                    entity_type="candidate",
                    entity_id=str(candidate_id),
                    details={"name": candidate.name, "email": candidate.email},
                )
                # Delete related records explicitly
                iids_result = await db.execute(
                    select(Interview.id).where(Interview.candidate_id == candidate_id)
                )
                iids = [r[0] for r in iids_result.all()]
                if iids:
                    await db.execute(delete(Report).where(Report.interview_id.in_(iids)))
                    await db.execute(delete(Transcription).where(Transcription.interview_id.in_(iids)))
                    await db.execute(delete(Analysis).where(Analysis.interview_id.in_(iids)))
                    await db.execute(delete(Interview).where(Interview.candidate_id == candidate_id))
                await db.execute(delete(Consent).where(Consent.candidate_id == candidate_id))
                await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
                results.append(
                    BulkActionResult(
                        candidate_id=candidate_id_str,
                        status="ok",
                        reason=None,
                    )
                )
                success_count += 1

        except Exception as e:
            results.append(
                BulkActionResult(
                    candidate_id=candidate_id_str,
                    status="error",
                    reason=str(e),
                )
            )
            failed_count += 1

    return BulkActionResponse(
        action=body.action,
        total=len(body.candidate_ids),
        success=success_count,
        failed=failed_count,
        details=results,
    )


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

    # Get all active positions except the candidate's current one
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

        # Calculate overlap
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
    # Parse and validate candidate IDs
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

    # Verify position exists and belongs to tenant
    result = await db.execute(
        select(Position).where(Position.id == position_id, Position.tenant_id == tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Poste introuvable")

    # Fetch all candidates in one query
    result = await db.execute(
        select(Candidate).where(
            Candidate.id.in_(parsed_ids),
            Candidate.tenant_id == tenant_id,
        )
    )
    candidates = {c.id: c for c in result.scalars().all()}

    # Validate all candidates found and belong to same position
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

    # Fetch latest interview for each candidate (subquery for latest per candidate)
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

    # Fetch analyses for those interviews
    interview_ids = [row.id for row in interviews.values()]
    analyses = {}
    if interview_ids:
        analysis_result = await db.execute(
            select(Analysis).where(Analysis.interview_id.in_(interview_ids))
        )
        for a in analysis_result.scalars().all():
            analyses[a.interview_id] = a

    # Fetch reports for candidates
    reports = {}
    if interview_ids:
        report_result = await db.execute(
            select(Report).where(Report.interview_id.in_(interview_ids))
        )
        for r in report_result.scalars().all():
            reports[r.interview_id] = r

    # Build response in requested order
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


# ---------------------------------------------------------------------------
# Phase 2 – Profil intrinseque : calcul + export PDF
# ---------------------------------------------------------------------------


@router.post("/candidates/{candidate_id}/profile/compute")
async def compute_profile(
    candidate_id: UUID,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Calcule le profil intrinseque du candidat via Claude.

    Analyse le cv_parsed_data pour extraire les competences, calculer un score
    intrinseque 0-100 et produire des suggestions d'amelioration CV.
    Le score est independant de tout poste (intrinseque au profil).
    """
    from starlette.concurrency import run_in_threadpool

    from app.services.profile_compute import compute_candidate_profile

    # Charger le candidat (tenant isolation)
    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    if not candidate.cv_parsed_data:
        raise HTTPException(
            status_code=400,
            detail="CV non analyse. Lancez d'abord l'analyse du CV.",
        )

    # Appel Claude (sync) wrappe pour ne pas bloquer l'event loop
    try:
        profile_data = await run_in_threadpool(
            compute_candidate_profile, candidate.cv_parsed_data
        )
    except ValueError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Erreur de parsing de la reponse Claude : {e}",
        )
    except Exception as e:
        import structlog
        _log = structlog.get_logger()
        _log.error("compute_profile_claude_error", candidate_id=str(candidate_id), error=str(e))
        raise HTTPException(
            status_code=502,
            detail="Erreur lors de l'appel a Claude. Veuillez reessayer.",
        )

    # Persister les resultats
    candidate.profile_score = profile_data.get("profile_score")
    candidate.profile_score_explanation = {
        "overall": profile_data.get("score_explanation", {}).get("overall", ""),
        "breakdown": profile_data.get("score_explanation", {}).get("breakdown", {}),
        "cv_quality_score": profile_data.get("cv_quality_score"),
        "cv_quality_details": profile_data.get("cv_quality_details", {}),
    }
    candidate.profile_competencies = profile_data.get("competencies", {})
    candidate.profile_suggestions = {
        "suggestions": profile_data.get("suggestions", []),
        "cv_quality_score": profile_data.get("cv_quality_score"),
        "cv_quality_details": profile_data.get("cv_quality_details", {}),
    }

    await log_action(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="compute_profile",
        entity_type="candidate",
        entity_id=str(candidate_id),
        details={"profile_score": candidate.profile_score},
    )

    await db.commit()
    await db.refresh(candidate)

    return {
        "candidate_id": str(candidate.id),
        "profile_score": candidate.profile_score,
        "profile_score_explanation": candidate.profile_score_explanation,
        "profile_competencies": candidate.profile_competencies,
        "profile_suggestions": candidate.profile_suggestions,
    }


@router.get("/candidates/{candidate_id}/profile/export")
async def export_profile_pdf(
    candidate_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Genere et retourne le dossier de competences PDF du candidat.

    Necessite que le profil ait ete calcule au prealable
    via POST /candidates/{id}/profile/compute.
    """
    import io
    from datetime import datetime, timezone

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm, mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.graphics.shapes import Drawing, Rect, String
    from reportlab.graphics import renderPDF

    result = await db.execute(
        select(Candidate).where(Candidate.id == candidate_id, Candidate.tenant_id == tenant_id)
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    if not candidate.profile_competencies:
        raise HTTPException(
            status_code=400,
            detail="Profil non calcule. Lancez d'abord POST /candidates/{id}/profile/compute.",
        )

    # --- Palette de couleurs (coherente avec pdf_report.py) ---
    BRAND_COLOR = colors.HexColor("#4F46E5")
    BRAND_LIGHT = colors.HexColor("#EEF2FF")
    GRAY_800 = colors.HexColor("#1F2937")
    GRAY_600 = colors.HexColor("#4B5563")
    GRAY_400 = colors.HexColor("#9CA3AF")
    GRAY_200 = colors.HexColor("#E5E7EB")
    GRAY_100 = colors.HexColor("#F3F4F6")
    GREEN = colors.HexColor("#16A34A")
    GREEN_LIGHT = colors.HexColor("#DCFCE7")
    ORANGE = colors.HexColor("#CA8A04")
    ORANGE_LIGHT = colors.HexColor("#FEF9C3")
    RED = colors.HexColor("#DC2626")
    WHITE = colors.white

    PAGE_W, PAGE_H = A4
    MARGIN = 1.5 * cm
    CONTENT_W = PAGE_W - 2 * MARGIN

    FOOTER_TEXT = (
        "Genere par AIHM -- Dossier de competences. "
        "Ce document est un outil d'aide a la decision. La decision finale revient au recruteur."
    )

    # --- Styles ---
    ss = getSampleStyleSheet()

    def _add_style(name, parent_name, **kwargs):
        if name not in ss.byName:
            ss.add(ParagraphStyle(name, parent=ss[parent_name], **kwargs))

    _add_style("Brand", "Heading1", fontSize=14, textColor=BRAND_COLOR, spaceAfter=1 * mm, leading=16)
    _add_style("SectionTitle", "Heading2", fontSize=9, textColor=BRAND_COLOR,
               spaceBefore=3 * mm, spaceAfter=1.5 * mm, leading=11)
    _add_style("Body8", "BodyText", fontSize=8, leading=10, textColor=GRAY_600)
    _add_style("Body8Bold", "BodyText", fontSize=8, leading=10, textColor=GRAY_800, fontName="Helvetica-Bold")
    _add_style("SmallGray", "BodyText", fontSize=6.5, textColor=GRAY_400, leading=8)
    _add_style("BulletItem", "BodyText", fontSize=8, leading=10, textColor=GRAY_600, leftIndent=8)
    _add_style("PriorityHigh", "BodyText", fontSize=8, leading=10,
               textColor=colors.HexColor("#DC2626"), leftIndent=8)
    _add_style("PriorityMed", "BodyText", fontSize=8, leading=10,
               textColor=colors.HexColor("#CA8A04"), leftIndent=8)
    _add_style("PriorityLow", "BodyText", fontSize=8, leading=10,
               textColor=colors.HexColor("#4B5563"), leftIndent=8)

    def _score_color(score):
        if score >= 70:
            return GREEN
        if score >= 50:
            return ORANGE
        return RED

    def _make_score_bar(label, score, bar_width=120):
        d = Drawing(CONTENT_W, 14)
        d.add(String(0, 3, label, fontSize=8, fontName="Helvetica", fillColor=GRAY_600))
        bar_x = 110
        d.add(Rect(bar_x, 2, bar_width, 10, fillColor=GRAY_200, strokeColor=None, strokeWidth=0))
        fill_w = max(1, bar_width * min(float(score), 100) / 100)
        fill_color = _score_color(float(score))
        d.add(Rect(bar_x, 2, fill_w, 10, fillColor=fill_color, strokeColor=None, strokeWidth=0))
        d.add(String(bar_x + bar_width + 6, 3, f"{int(score)}/100",
                     fontSize=8, fontName="Helvetica-Bold", fillColor=fill_color))
        return d

    def _divider():
        d = Drawing(CONTENT_W, 3)
        d.add(Rect(0, 1, CONTENT_W, 0.8, fillColor=BRAND_LIGHT, strokeColor=None, strokeWidth=0))
        return d

    def _level_dots(level, max_level=5):
        filled = min(int(level), max_level)
        empty = max_level - filled
        return "\u25CF" * filled + "\u25CB" * empty

    def _add_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 6)
        canvas.setFillColor(GRAY_400)
        canvas.drawString(MARGIN, 12 * mm, FOOTER_TEXT)
        canvas.drawRightString(PAGE_W - MARGIN, 12 * mm, f"Page {doc.page}")
        canvas.setStrokeColor(GRAY_200)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, 16 * mm, PAGE_W - MARGIN, 16 * mm)
        canvas.restoreState()

    # --- Construction du PDF ---
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=20 * mm,
    )
    story = []
    now_str = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    competencies = candidate.profile_competencies or {}
    score_expl = candidate.profile_score_explanation or {}
    suggestions_data = candidate.profile_suggestions or {}
    suggestions = suggestions_data.get("suggestions", [])
    cv_quality_score = suggestions_data.get("cv_quality_score")
    cv_quality_details = suggestions_data.get("cv_quality_details", {})
    breakdown = score_expl.get("breakdown", {})

    # Header
    story.append(Paragraph("AIHM", ss["Brand"]))
    story.append(Spacer(1, 1 * mm))

    # Fiche identite
    info_data = [
        [
            Paragraph(f"<b>Candidat :</b> {candidate.name}", ss["Body8"]),
            Paragraph(f"<b>Email :</b> {candidate.email or '—'}", ss["Body8"]),
        ],
        [
            Paragraph(f"<b>Telephone :</b> {candidate.phone or '—'}", ss["Body8"]),
            Paragraph(f"<b>Date du rapport :</b> {now_str}", ss["Body8"]),
        ],
    ]
    info_table = Table(info_data, colWidths=[CONTENT_W / 2] * 2)
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, BRAND_COLOR),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 3 * mm))

    # Score global + breakdown
    if candidate.profile_score is not None:
        story.append(_divider())
        story.append(Paragraph("Score profil intrinseque", ss["SectionTitle"]))
        story.append(_make_score_bar("Score global", candidate.profile_score))

        for dim_key, dim_label in [
            ("technical_depth", "Profondeur technique"),
            ("experience_quality", "Qualite de l'experience"),
            ("education_relevance", "Formation"),
            ("cv_completeness", "Completude du CV"),
        ]:
            dim_data = breakdown.get(dim_key, {})
            dim_score = dim_data.get("score")
            if dim_score is not None:
                story.append(_make_score_bar(dim_label, dim_score))

        if score_expl.get("overall"):
            story.append(Spacer(1, 2 * mm))
            story.append(Paragraph(score_expl["overall"], ss["Body8"]))

        # Details breakdown
        for dim_key, dim_label in [
            ("technical_depth", "Profondeur technique"),
            ("experience_quality", "Qualite de l'experience"),
            ("education_relevance", "Formation"),
            ("cv_completeness", "Completude du CV"),
        ]:
            dim_data = breakdown.get(dim_key, {})
            if dim_data.get("detail"):
                story.append(Paragraph(
                    f'<b>{dim_label} :</b> {dim_data["detail"]}', ss["Body8"]
                ))
        story.append(Spacer(1, 2 * mm))

    # Qualite du CV
    if cv_quality_score is not None:
        story.append(_divider())
        story.append(Paragraph("Qualite du document CV", ss["SectionTitle"]))
        story.append(_make_score_bar("Score qualite CV", cv_quality_score))
        for qkey, qlabel in [
            ("completeness", "Completude"),
            ("clarity", "Clarte"),
            ("impact", "Impact / chiffres"),
            ("consistency", "Coherence"),
        ]:
            qval = cv_quality_details.get(qkey)
            if qval is not None:
                story.append(_make_score_bar(qlabel, qval))
        story.append(Spacer(1, 2 * mm))

    # Competences techniques
    technical = competencies.get("technical", [])
    if technical:
        story.append(_divider())
        story.append(Paragraph("Competences techniques", ss["SectionTitle"]))
        tech_header = [
            Paragraph("<b>Competence</b>", ss["Body8Bold"]),
            Paragraph("<b>Niveau</b>", ss["Body8Bold"]),
            Paragraph("<b>Demontre</b>", ss["Body8Bold"]),
            Paragraph("<b>Justification</b>", ss["Body8Bold"]),
        ]
        tech_data = [tech_header]
        for skill in technical:
            level = skill.get("level", 0)
            demonstrated = skill.get("demonstrated", False)
            dem_text = "\u2713 Oui" if demonstrated else "\u2717 Non"
            dem_color = "#16A34A" if demonstrated else "#DC2626"
            tech_data.append([
                Paragraph(f'<b>{skill.get("name", "")}</b>', ss["Body8Bold"]),
                Paragraph(_level_dots(level) + f" {level}/5", ss["Body8"]),
                Paragraph(f'<font color="{dem_color}">{dem_text}</font>', ss["Body8"]),
                Paragraph(str(skill.get("evidence", ""))[:100], ss["Body8"]),
            ])
        col_w = [2.8 * cm, 2.2 * cm, 2 * cm, CONTENT_W - 7 * cm]
        tech_table = Table(tech_data, colWidths=col_w)
        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_COLOR),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("LEADING", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.3, GRAY_200),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        for i in range(1, len(tech_data)):
            bg = GRAY_100 if i % 2 == 0 else WHITE
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), bg))
        tech_table.setStyle(TableStyle(style_cmds))
        story.append(tech_table)
        story.append(Spacer(1, 2 * mm))

    # Soft skills
    soft_skills = competencies.get("soft_skills", [])
    if soft_skills:
        story.append(_divider())
        story.append(Paragraph("Competences comportementales observees", ss["SectionTitle"]))
        for ss_item in soft_skills:
            story.append(Paragraph(f"\u2022 {ss_item}", ss["BulletItem"]))
        story.append(Spacer(1, 2 * mm))

    # Experience professionnelle
    experience = competencies.get("experience", [])
    if experience:
        story.append(_divider())
        story.append(Paragraph("Experience professionnelle", ss["SectionTitle"]))
        for exp in experience:
            duration = exp.get("duration_months", 0)
            years = duration // 12
            months = duration % 12
            dur_str = ""
            if years:
                dur_str += f"{years} an{'s' if years > 1 else ''}"
            if months:
                dur_str += f" {months} mois"
            if not dur_str:
                dur_str = "Duree non precisee"

            title_line = f'<b>{exp.get("title", "")}</b>'
            if exp.get("company"):
                title_line += f' — {exp["company"]}'
            if dur_str:
                title_line += f' <font color="#9CA3AF">({dur_str.strip()})</font>'
            story.append(Paragraph(title_line, ss["Body8Bold"]))

            for resp in (exp.get("responsibilities") or [])[:3]:
                story.append(Paragraph(f"\u2022 {resp}", ss["BulletItem"]))
            for ach in (exp.get("key_achievements") or [])[:2]:
                story.append(Paragraph(
                    f'<font color="#16A34A">\u2605</font> {ach}',
                    ss["BulletItem"],
                ))
            story.append(Spacer(1, 1.5 * mm))

    # Formation
    education = competencies.get("education", [])
    if education:
        story.append(_divider())
        story.append(Paragraph("Formation", ss["SectionTitle"]))
        for edu in education:
            year = edu.get("year", "")
            line = f'<b>{edu.get("degree", "")}</b>'
            if edu.get("field"):
                line += f' en {edu["field"]}'
            if edu.get("institution"):
                line += f' — {edu["institution"]}'
            if year:
                line += f' ({year})'
            story.append(Paragraph(line, ss["Body8"]))
        story.append(Spacer(1, 2 * mm))

    # Langues
    languages = competencies.get("languages", [])
    if languages:
        story.append(_divider())
        story.append(Paragraph("Langues", ss["SectionTitle"]))
        lang_items = [f'{lg.get("name", "")} : {lg.get("level", "")}' for lg in languages]
        story.append(Paragraph(" | ".join(lang_items), ss["Body8"]))
        story.append(Spacer(1, 2 * mm))

    # Suggestions d'amelioration
    if suggestions:
        story.append(_divider())
        story.append(Paragraph("Suggestions d'amelioration du CV", ss["SectionTitle"]))
        priority_labels = {"high": "PRIORITAIRE", "medium": "CONSEILLE", "low": "OPTIONNEL"}
        priority_colors = {
            "high": "#DC2626",
            "medium": "#CA8A04",
            "low": "#4B5563",
        }
        for sug in suggestions:
            priority = sug.get("priority", "low")
            category = sug.get("category", "")
            label = priority_labels.get(priority, priority.upper())
            color = priority_colors.get(priority, "#4B5563")
            text = (
                f'<font color="{color}"><b>[{label}]</b></font> '
                f'<i>{category}</i> — {sug.get("suggestion", "")}'
            )
            story.append(Paragraph(text, ss["BulletItem"]))
        story.append(Spacer(1, 2 * mm))

    # Disclaimer
    story.append(Spacer(1, 3 * mm))
    story.append(Paragraph(
        "<i>Ce dossier de competences est genere par IA a titre informatif. "
        "Il ne constitue pas une recommandation d'embauche ou de rejet. "
        "La decision finale revient au recruteur.</i>",
        ss["SmallGray"],
    ))

    doc.build(story, onFirstPage=_add_footer, onLaterPages=_add_footer)
    pdf_bytes = buf.getvalue()

    safe_name = candidate.name.replace(" ", "_").replace("/", "_")
    filename = f"dossier_competences_{safe_name}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
    from app.models.match_score import MatchScore, MatchSession
    from app.schemas.batch_matching import MatchSessionResponse

    tenant_id = current_user.tenant_id

    # Vérifier que le candidat appartient au tenant et a un CV parsé
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
            detail="Le candidat n'a pas de CV analysé. Impossible de lancer le matching.",
        )

    # Résoudre les postes
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
        # Tous les postes actifs du tenant
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
            detail="Aucun poste actif trouvé pour ce tenant",
        )

    total_pairs = len(position_uuids)

    # Calculer les paires manquantes si pas force_recompute
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

    # Créer la session de matching
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

    # Lancer le worker Celery, fallback inline si indisponible
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
