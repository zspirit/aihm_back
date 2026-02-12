import asyncio
import csv
import io
import json
import secrets
from uuid import UUID

from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db, async_session
from app.core.dependencies import get_current_user, get_tenant_id, require_role
from app.models.candidate import Candidate
from app.models.consent import Consent
from app.models.position import Position
from app.models.user import User
from app.schemas.candidate import CandidateListResponse, CandidateResponse, PaginatedCandidates
from app.services.storage import upload_file

TERMINAL_STATUSES = {"cv_analyzed", "evaluated", "call_done"}

router = APIRouter(tags=["candidates"])
settings = get_settings()


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

    query = select(Candidate).where(
        Candidate.position_id == position_id,
        Candidate.tenant_id == tenant_id,
    )
    count_query = select(func.count()).select_from(Candidate).where(
        Candidate.position_id == position_id,
        Candidate.tenant_id == tenant_id,
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

        from app.workers.cv_processing import process_cv

        process_cv.delay(str(candidate.id))

        created.append({
            "id": str(candidate.id),
            "name": candidate.name,
            "cv_file_path": candidate.cv_file_path,
        })

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
        writer.writerow([
            c.name,
            c.email or "",
            c.phone or "",
            round(c.cv_score, 1) if c.cv_score is not None else "",
            c.pipeline_status,
            c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else "",
        ])

    csv_content = output.getvalue()
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="candidats_{position_id}.csv"'},
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


@router.post("/candidates/{candidate_id}/grant-consent")
async def grant_consent_admin(
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

    from datetime import datetime, timezone

    consents_result = await db.execute(
        select(Consent).where(Consent.candidate_id == candidate_id)
    )
    consents = consents_result.scalars().all()
    for consent in consents:
        if not consent.granted:
            consent.granted = True
            consent.granted_at = datetime.now(timezone.utc)
            consent.channel = "admin"

    candidate.pipeline_status = "consent_given"
    return {"status": "ok", "consents_granted": len(consents)}


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
