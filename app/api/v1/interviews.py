from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_tenant_id
from app.models.analysis import Analysis
from app.models.candidate import Candidate
from app.models.consent import Consent
from app.models.interview import Interview
from app.models.report import Report
from app.models.transcription import Transcription
from app.schemas.interview import (
    AnalysisResponse,
    InterviewCreate,
    InterviewResponse,
    ReportResponse,
    TranscriptionResponse,
)

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

    attempts = await db.execute(
        select(Interview).where(Interview.candidate_id == candidate_id)
    )
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

    report_result = await db.execute(
        select(Report).where(Report.interview_id == interview_id)
    )
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
