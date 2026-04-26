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
from app.models.analysis import Analysis
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.consent import Consent
from app.models.interview import Interview
from app.models.match_score import MatchScore
from app.models.position import Position
from app.models.report import Report
from app.models.transcription import Transcription
from app.models.user import User
from app.schemas.bulk_import import BulkActionRequest, BulkActionResponse, BulkActionResult
from app.schemas.candidate import (
    CandidateGlobalListResponse,
    CandidateInterviewResponse,
    CandidateListResponse,
    CandidateResponse,
    CandidateUpdate,
    InterviewStatsResponse,
    PaginatedCandidates,
    PaginatedCandidatesGlobal,
)
from app.services.audit import log_action
from app.services.storage import upload_file

from ._helpers import ALLOWED_CV_EXTENSIONS, MAX_CV_SIZE, TERMINAL_STATUSES

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
        # Include candidates linked via Application table OR direct position_id
        from sqlalchemy import exists
        app_exists = exists().where(
            Application.candidate_id == Candidate.id,
            Application.position_id == position_id,
        )
        pos_filter = or_(Candidate.position_id == position_id, app_exists)
        query = query.where(pos_filter)
        count_query = count_query.where(pos_filter)

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

    # Include candidates linked via Application table OR direct position_id
    from sqlalchemy import exists
    app_exists = exists().where(
        Application.candidate_id == Candidate.id,
        Application.position_id == position_id,
    )
    pos_filter = or_(Candidate.position_id == position_id, app_exists)

    query = (
        select(Candidate, func.count(Interview.id).label("interview_count"))
        .outerjoin(Interview, Candidate.id == Interview.candidate_id)
        .where(
            pos_filter,
            Candidate.tenant_id == tenant_id,
        )
        .group_by(Candidate.id)
    )
    count_query = (
        select(func.count())
        .select_from(Candidate)
        .where(
            pos_filter,
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
        ext = os.path.splitext(cv.filename or "")[1].lower()
        if ext not in ALLOWED_CV_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail="Format de fichier non supporte. Formats acceptes: PDF, DOC, DOCX",
            )

        contents = await cv.read()
        if len(contents) > MAX_CV_SIZE:
            raise HTTPException(status_code=400, detail="Le fichier ne doit pas depasser 10 MB")
        await cv.seek(0)

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
            pass

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

        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_CV_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Format de fichier non supporte pour '{filename}'. Formats acceptes: PDF, DOC, DOCX",
            )

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
            pass

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
        summary_json=candidate.summary_json,
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

    duration_result = (
        await db.execute(
            select(func.avg(Interview.duration_seconds))
            .where(Interview.candidate_id == candidate_id, Interview.duration_seconds.isnot(None))
        )
    ).scalar()
    average_duration_seconds = int(duration_result) if duration_result is not None else None

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
        summary_json=candidate.summary_json,
    )


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

    # Collect file paths to delete from storage
    storage_paths = []
    if candidate.cv_file_path:
        storage_paths.append(candidate.cv_file_path)

    interview_ids_result = await db.execute(
        select(Interview).where(Interview.candidate_id == candidate_id)
    )
    interviews = interview_ids_result.scalars().all()
    interview_ids = [i.id for i in interviews]
    for interview in interviews:
        if getattr(interview, "audio_path", None):
            storage_paths.append(interview.audio_path)

    if interview_ids:
        # Collect report PDF paths
        report_result = await db.execute(
            select(Report).where(Report.interview_id.in_(interview_ids))
        )
        for report in report_result.scalars().all():
            if getattr(report, "pdf_path", None):
                storage_paths.append(report.pdf_path)

        await db.execute(delete(Report).where(Report.interview_id.in_(interview_ids)))
        await db.execute(delete(Transcription).where(Transcription.interview_id.in_(interview_ids)))
        await db.execute(delete(Analysis).where(Analysis.interview_id.in_(interview_ids)))
        await db.execute(delete(Interview).where(Interview.candidate_id == candidate_id))

    await db.execute(delete(Consent).where(Consent.candidate_id == candidate_id))
    await db.execute(delete(MatchScore).where(MatchScore.candidate_id == candidate_id))

    from app.models.application import Application
    await db.execute(delete(Application).where(Application.candidate_id == candidate_id))

    await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
    await db.commit()

    # Delete files from storage (after commit, non-blocking)
    if storage_paths:
        import asyncio as _asyncio
        async def _cleanup_storage():
            try:
                from app.services.storage import s3_client
                for path in storage_paths:
                    parts = path.split("/", 1)
                    if len(parts) == 2:
                        try:
                            s3_client.remove_object(parts[0], parts[1])
                        except Exception:
                            pass
            except Exception:
                pass
        _asyncio.create_task(_cleanup_storage())


@router.post("/candidates/bulk-delete", status_code=status.HTTP_200_OK)
async def bulk_delete_candidates(
    body: dict,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple candidates by IDs."""
    candidate_ids = body.get("ids", [])
    if not candidate_ids:
        raise HTTPException(status_code=400, detail="Aucun ID fourni")
    if len(candidate_ids) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 candidats par suppression")

    uuids = [UUID(cid) for cid in candidate_ids]

    result = await db.execute(
        select(Candidate).where(
            Candidate.id.in_(uuids),
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidates = result.scalars().all()
    found_ids = [c.id for c in candidates]

    if not found_ids:
        raise HTTPException(status_code=404, detail="Aucun candidat trouve")

    int_result = await db.execute(
        select(Interview.id).where(Interview.candidate_id.in_(found_ids))
    )
    interview_ids = [row[0] for row in int_result.all()]

    if interview_ids:
        await db.execute(delete(Report).where(Report.interview_id.in_(interview_ids)))
        await db.execute(delete(Transcription).where(Transcription.interview_id.in_(interview_ids)))
        await db.execute(delete(Analysis).where(Analysis.interview_id.in_(interview_ids)))
        await db.execute(delete(Interview).where(Interview.candidate_id.in_(found_ids)))

    await db.execute(delete(Consent).where(Consent.candidate_id.in_(found_ids)))
    await db.execute(delete(MatchScore).where(MatchScore.candidate_id.in_(found_ids)))

    from app.models.application import Application
    await db.execute(delete(Application).where(Application.candidate_id.in_(found_ids)))

    await db.execute(delete(Candidate).where(Candidate.id.in_(found_ids)))

    for c in candidates:
        await log_action(
            db, tenant_id=current_user.tenant_id, user_id=current_user.id,
            action="delete_candidate", entity_type="candidate",
            entity_id=str(c.id), details={"name": c.name},
        )

    await db.commit()
    return {"deleted": len(found_ids)}


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

                try:
                    from app.workers.telephony import initiate_call

                    initiate_call.delay(str(interview.id))
                except Exception:
                    pass

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
