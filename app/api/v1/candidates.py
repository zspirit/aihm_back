import asyncio
import json
import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db, async_session
from app.core.dependencies import get_current_user, get_tenant_id, require_role
from app.models.candidate import Candidate
from app.models.consent import Consent
from app.models.position import Position
from app.models.user import User
from app.schemas.candidate import CandidateListResponse, CandidateResponse
from app.services.storage import upload_file

TERMINAL_STATUSES = {"cv_analyzed", "evaluated", "call_done"}

router = APIRouter(tags=["candidates"])
settings = get_settings()


@router.get("/positions/{position_id}/candidates", response_model=list[CandidateListResponse])
async def list_candidates(
    position_id: UUID,
    sort_by: str = "cv_score",
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Position).where(Position.id == position_id, Position.tenant_id == tenant_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Poste introuvable")

    query = select(Candidate).where(
        Candidate.position_id == position_id,
        Candidate.tenant_id == tenant_id,
    )
    if sort_by == "cv_score":
        query = query.order_by(Candidate.cv_score.desc().nulls_last())
    else:
        query = query.order_by(Candidate.created_at.desc())

    result = await db.execute(query)
    return [
        CandidateListResponse(
            id=str(c.id),
            name=c.name,
            email=c.email,
            phone=c.phone,
            cv_score=c.cv_score,
            pipeline_status=c.pipeline_status,
            created_at=c.created_at,
        )
        for c in result.scalars().all()
    ]


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
        from app.workers.cv_processing import process_cv

        process_cv.delay(str(candidate.id))

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

    # Fetch latest interview for this candidate
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
        position_id=str(candidate.position_id),
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
    )


@router.delete("/candidates/{candidate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_candidate(
    candidate_id: UUID,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Candidate).where(Candidate.id == candidate_id, Candidate.tenant_id == current_user.tenant_id)
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")
    await db.delete(candidate)


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
                # Also fetch latest interview_id
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
                yield f"event: update\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
                if candidate.pipeline_status in TERMINAL_STATUSES:
                    yield f"event: done\ndata: {json.dumps({'status': candidate.pipeline_status})}\n\n"
                    break
            await asyncio.sleep(3)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
