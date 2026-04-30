"""Psychometric assessment endpoints — Phase 4.1.

POST /interviews/{id}/psychometrics  submit (one per interview)
GET  /interviews/{id}/psychometrics  read

The Claude follow-up that fills traits_json + turnover_risk runs async
via a Celery task — not started here, that wiring belongs to whatever
worker module owns interview-completion side-effects. The submit endpoint
returns 202 to make the deferred-analysis behavior obvious.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.interview import Interview
from app.models.psychometric import PsychometricAssessment
from app.models.user import User

router = APIRouter(tags=["psychometrics"])


class PsychometricSubmit(BaseModel):
    score_communication: int = Field(..., ge=1, le=5)
    score_problem_solving: int = Field(..., ge=1, le=5)
    score_team_fit: int = Field(..., ge=1, le=5)
    score_stress_handling: int = Field(..., ge=1, le=5)
    score_leadership: int = Field(..., ge=1, le=5)


class PsychometricResponse(BaseModel):
    id: UUID
    interview_id: UUID
    candidate_id: UUID
    submitted_by: UUID
    score_communication: int
    score_problem_solving: int
    score_team_fit: int
    score_stress_handling: int
    score_leadership: int
    traits_json: Optional[dict] = None
    turnover_risk: Optional[str] = None
    created_at: datetime
    analyzed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


@router.post(
    "/interviews/{interview_id}/psychometrics",
    response_model=PsychometricResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_psychometric(
    interview_id: UUID,
    payload: PsychometricSubmit,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    interview = await db.get(Interview, interview_id)
    if interview is None or interview.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="interview not found")

    # One assessment per interview (UniqueConstraint at the DB level too).
    existing = (
        await db.execute(
            select(PsychometricAssessment).where(
                PsychometricAssessment.interview_id == interview_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="psychometric already submitted")

    assessment = PsychometricAssessment(
        tenant_id=current_user.tenant_id,
        interview_id=interview_id,
        candidate_id=interview.candidate_id,
        submitted_by=current_user.id,
        score_communication=payload.score_communication,
        score_problem_solving=payload.score_problem_solving,
        score_team_fit=payload.score_team_fit,
        score_stress_handling=payload.score_stress_handling,
        score_leadership=payload.score_leadership,
    )
    db.add(assessment)
    await db.commit()
    await db.refresh(assessment)

    # NOTE: a downstream worker should call psychometrics_analysis.delay(assessment.id)
    # to populate traits_json + turnover_risk. Wired up where interview-complete
    # side effects are owned. Not triggered here so the endpoint stays useful
    # in setups that don't run the LLM tier (e.g. local dev).
    return assessment


@router.get(
    "/interviews/{interview_id}/psychometrics",
    response_model=PsychometricResponse,
)
async def get_psychometric(
    interview_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    interview = await db.get(Interview, interview_id)
    if interview is None or interview.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="interview not found")

    assessment = (
        await db.execute(
            select(PsychometricAssessment).where(
                PsychometricAssessment.interview_id == interview_id
            )
        )
    ).scalar_one_or_none()
    if assessment is None:
        raise HTTPException(status_code=404, detail="no assessment yet")
    return assessment
