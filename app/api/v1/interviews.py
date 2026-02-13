from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_tenant_id
from app.models.analysis import Analysis
from app.models.candidate import Candidate
from app.models.consent import Consent
from app.models.interview import Interview
from app.models.position import Position
from app.models.report import Report
from app.models.transcription import Transcription
from app.schemas.interview import (
    AnalysisResponse,
    InterviewCreate,
    InterviewListItem,
    InterviewResponse,
    InterviewUpdate,
    PaginatedInterviews,
    ReportResponse,
    TranscriptionResponse,
)
from app.services.storage import download_file

router = APIRouter(tags=["interviews"])


@router.post(
    "/candidates/{candidate_id}/interviews",
    response_model=InterviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def schedule_interview(
    candidate_id: UUID,
    data: InterviewCreate,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Candidate).where(Candidate.id == candidate_id, Candidate.tenant_id == tenant_id)
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    if data.phone:
        candidate.phone = data.phone

    if not candidate.phone:
        raise HTTPException(status_code=400, detail="Le candidat n'a pas de numero de telephone")

    consent_result = await db.execute(
        select(Consent).where(
            Consent.candidate_id == candidate_id,
            Consent.type == "call_recording",
            Consent.granted.is_(True),
        )
    )
    if not consent_result.scalar_one_or_none():
        raise HTTPException(
            status_code=400, detail="Le candidat n'a pas donne son consentement pour l'appel"
        )

    attempts = await db.execute(select(Interview).where(Interview.candidate_id == candidate_id))
    attempt_count = len(attempts.scalars().all())
    if attempt_count >= 3:
        raise HTTPException(status_code=400, detail="Nombre maximum de tentatives atteint (3)")

    interview = Interview(
        candidate_id=candidate_id,
        position_id=candidate.position_id,
        tenant_id=tenant_id,
        scheduled_at=data.scheduled_at,
        attempt_number=attempt_count + 1,
    )
    db.add(interview)
    await db.flush()

    candidate.pipeline_status = "call_scheduled"

    from app.workers.telephony import initiate_call

    initiate_call.delay(str(interview.id))

    return InterviewResponse(
        id=str(interview.id),
        candidate_id=str(interview.candidate_id),
        position_id=str(interview.position_id),
        status=interview.status,
        scheduled_at=interview.scheduled_at,
        started_at=interview.started_at,
        ended_at=interview.ended_at,
        duration_seconds=interview.duration_seconds,
        questions_asked=interview.questions_asked,
        attempt_number=interview.attempt_number,
        created_at=interview.created_at,
    )


@router.get("/interviews", response_model=PaginatedInterviews)
async def list_interviews(
    status: str | None = Query(None),
    position_id: UUID | None = Query(None),
    candidate_name: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    sort_by: str = Query("created_at"),
    sort_order: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    # Base query with joins
    base_query = (
        select(
            Interview,
            Candidate.name.label("candidate_name"),
            Position.title.label("position_title"),
            func.count(Report.id).label("report_count"),
        )
        .join(Candidate, Interview.candidate_id == Candidate.id)
        .join(Position, Interview.position_id == Position.id)
        .outerjoin(Report, Interview.id == Report.interview_id)
        .where(Interview.tenant_id == tenant_id)
    )

    # Apply filters
    if status:
        base_query = base_query.where(Interview.status == status)
    if position_id:
        base_query = base_query.where(Interview.position_id == position_id)
    if candidate_name:
        base_query = base_query.where(Candidate.name.ilike(f"%{candidate_name}%"))
    if date_from:
        base_query = base_query.where(Interview.created_at >= date_from)
    if date_to:
        base_query = base_query.where(Interview.created_at <= date_to)

    # Group by
    base_query = base_query.group_by(Interview.id, Candidate.name, Position.title)

    # Count query for total
    count_query = (
        select(func.count(func.distinct(Interview.id)))
        .select_from(Interview)
        .join(Candidate, Interview.candidate_id == Candidate.id)
        .join(Position, Interview.position_id == Position.id)
        .where(Interview.tenant_id == tenant_id)
    )
    if status:
        count_query = count_query.where(Interview.status == status)
    if position_id:
        count_query = count_query.where(Interview.position_id == position_id)
    if candidate_name:
        count_query = count_query.where(Candidate.name.ilike(f"%{candidate_name}%"))
    if date_from:
        count_query = count_query.where(Interview.created_at >= date_from)
    if date_to:
        count_query = count_query.where(Interview.created_at <= date_to)

    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Sort
    sort_column = getattr(Interview, sort_by, Interview.created_at)
    if sort_order == "asc":
        base_query = base_query.order_by(sort_column.asc())
    else:
        base_query = base_query.order_by(sort_column.desc())

    # Paginate
    base_query = base_query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(base_query)
    rows = result.all()

    items = [
        InterviewListItem(
            id=str(row.Interview.id),
            candidate_id=str(row.Interview.candidate_id),
            candidate_name=row.candidate_name,
            position_id=str(row.Interview.position_id),
            position_title=row.position_title,
            status=row.Interview.status,
            scheduled_at=row.Interview.scheduled_at,
            started_at=row.Interview.started_at,
            ended_at=row.Interview.ended_at,
            duration_seconds=row.Interview.duration_seconds,
            attempt_number=row.Interview.attempt_number,
            has_report=row.report_count > 0,
            created_at=row.Interview.created_at,
        )
        for row in rows
    ]

    return PaginatedInterviews(items=items, total=total, page=page, page_size=page_size)


@router.patch("/interviews/{interview_id}", response_model=InterviewResponse)
async def reschedule_interview(
    interview_id: UUID,
    data: InterviewUpdate,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.tenant_id == tenant_id)
    )
    interview = result.scalar_one_or_none()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview introuvable")

    if interview.status != "scheduled":
        raise HTTPException(
            status_code=400, detail="Seuls les entretiens planifies peuvent etre replanifies"
        )

    interview.scheduled_at = data.scheduled_at
    await db.flush()

    return InterviewResponse(
        id=str(interview.id),
        candidate_id=str(interview.candidate_id),
        position_id=str(interview.position_id),
        status=interview.status,
        scheduled_at=interview.scheduled_at,
        started_at=interview.started_at,
        ended_at=interview.ended_at,
        duration_seconds=interview.duration_seconds,
        questions_asked=interview.questions_asked,
        attempt_number=interview.attempt_number,
        created_at=interview.created_at,
    )


@router.delete("/interviews/{interview_id}", status_code=204)
async def cancel_interview(
    interview_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.tenant_id == tenant_id)
    )
    interview = result.scalar_one_or_none()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview introuvable")

    if interview.status != "scheduled":
        raise HTTPException(
            status_code=400, detail="Seuls les entretiens planifies peuvent etre annules"
        )

    interview.status = "cancelled"
    await db.flush()


@router.get("/interviews/{interview_id}", response_model=InterviewResponse)
async def get_interview(
    interview_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.tenant_id == tenant_id)
    )
    interview = result.scalar_one_or_none()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview introuvable")

    return InterviewResponse(
        id=str(interview.id),
        candidate_id=str(interview.candidate_id),
        position_id=str(interview.position_id),
        status=interview.status,
        scheduled_at=interview.scheduled_at,
        started_at=interview.started_at,
        ended_at=interview.ended_at,
        duration_seconds=interview.duration_seconds,
        questions_asked=interview.questions_asked,
        attempt_number=interview.attempt_number,
        created_at=interview.created_at,
    )


@router.get("/interviews/{interview_id}/transcription", response_model=TranscriptionResponse)
async def get_transcription(
    interview_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.tenant_id == tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Interview introuvable")

    trans_result = await db.execute(
        select(Transcription).where(Transcription.interview_id == interview_id)
    )
    transcription = trans_result.scalar_one_or_none()
    if not transcription:
        raise HTTPException(status_code=404, detail="Transcription non disponible")

    return TranscriptionResponse(
        id=str(transcription.id),
        interview_id=str(transcription.interview_id),
        full_text=transcription.full_text,
        segments=transcription.segments,
        language_detected=transcription.language_detected,
        confidence_score=transcription.confidence_score,
    )


@router.get("/interviews/{interview_id}/analysis", response_model=AnalysisResponse)
async def get_analysis(
    interview_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.tenant_id == tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Interview introuvable")

    analysis_result = await db.execute(
        select(Analysis).where(Analysis.interview_id == interview_id)
    )
    analysis = analysis_result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analyse non disponible")

    return AnalysisResponse(
        id=str(analysis.id),
        interview_id=str(analysis.interview_id),
        skills_extracted=analysis.skills_extracted,
        experience_examples=analysis.experience_examples,
        communication_indicators=analysis.communication_indicators,
        scores=analysis.scores,
        score_explanations=analysis.score_explanations,
    )


@router.get("/interviews/{interview_id}/report", response_model=ReportResponse)
async def get_report(
    interview_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.tenant_id == tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Interview introuvable")

    report_result = await db.execute(select(Report).where(Report.interview_id == interview_id))
    report = report_result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="Rapport non disponible")

    return ReportResponse(
        id=str(report.id),
        candidate_id=str(report.candidate_id),
        interview_id=str(report.interview_id),
        content=report.content,
        pdf_file_path=report.pdf_file_path,
        generated_at=report.generated_at,
    )


@router.get("/interviews/{interview_id}/audio")
async def get_audio(
    interview_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.tenant_id == tenant_id)
    )
    interview = result.scalar_one_or_none()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview introuvable")

    if not interview.audio_file_path:
        raise HTTPException(status_code=404, detail="Audio non disponible")

    parts = interview.audio_file_path.split("/", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=404, detail="Chemin audio invalide")

    try:
        data = download_file(parts[0], parts[1])
    except Exception:
        raise HTTPException(status_code=404, detail="Fichier audio introuvable")

    return Response(
        content=data,
        media_type="audio/mpeg",
        headers={"Content-Disposition": f'inline; filename="interview_{interview_id}.mp3"'},
    )


@router.get("/interviews/{interview_id}/report/download")
async def download_report_pdf(
    interview_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Interview).where(Interview.id == interview_id, Interview.tenant_id == tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Interview introuvable")

    report_result = await db.execute(select(Report).where(Report.interview_id == interview_id))
    report = report_result.scalar_one_or_none()
    if not report or not report.content:
        raise HTTPException(status_code=404, detail="Rapport non disponible")

    # Try to serve existing PDF from storage
    if report.pdf_file_path:
        parts = report.pdf_file_path.split("/", 1)
        if len(parts) == 2:
            try:
                data = download_file(parts[0], parts[1])
                return Response(
                    content=data,
                    media_type="application/pdf",
                    headers={
                        "Content-Disposition": f'attachment; filename="rapport_{interview_id}.pdf"'
                    },
                )
            except Exception:
                pass

    # Fallback: generate PDF on-the-fly from JSON content
    from app.services.pdf_report import generate_pdf

    data = generate_pdf(report.content)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="rapport_{interview_id}.pdf"'},
    )
