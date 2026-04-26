"""Email sequences endpoints — Phase 2.2.

CRUD sequences + steps + enroll candidates.
Worker Celery (separe) consomme les enrollments dus via process_sequence_step.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.email_sequence import EmailSequence, SequenceEnrollment, SequenceStep
from app.models.email_template import EmailTemplate
from app.models.user import User

router = APIRouter(prefix="/email-sequences", tags=["email-sequences"])


class StepInput(BaseModel):
    template_id: UUID
    order_index: int = 0
    delay_hours: int = Field(24, ge=0, le=24 * 365)


class SequenceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    trigger: str
    is_active: bool = True
    steps: list[StepInput] = []


class SequenceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    trigger: Optional[str] = None
    is_active: Optional[bool] = None


class StepResponse(BaseModel):
    id: UUID
    template_id: UUID
    template_name: Optional[str] = None
    order_index: int
    delay_hours: int

    class Config:
        from_attributes = True


class SequenceResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: Optional[str] = None
    trigger: str
    is_active: bool
    steps: list[StepResponse] = []
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


@router.get("", response_model=list[SequenceResponse])
async def list_sequences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(EmailSequence).where(EmailSequence.tenant_id == current_user.tenant_id)
        .order_by(desc(EmailSequence.created_at))
    )
    seqs = list(res.scalars().all())
    if not seqs:
        return []

    # Charge steps + templates names en bulk
    seq_ids = [s.id for s in seqs]
    steps_res = await db.execute(
        select(SequenceStep, EmailTemplate.name)
        .outerjoin(EmailTemplate, EmailTemplate.id == SequenceStep.template_id)
        .where(SequenceStep.sequence_id.in_(seq_ids))
        .order_by(SequenceStep.order_index)
    )
    steps_by_seq: dict[UUID, list[StepResponse]] = {}
    for step, tpl_name in steps_res.all():
        steps_by_seq.setdefault(step.sequence_id, []).append(
            StepResponse(
                id=step.id,
                template_id=step.template_id,
                template_name=tpl_name,
                order_index=step.order_index,
                delay_hours=step.delay_hours,
            )
        )

    return [
        SequenceResponse(
            id=s.id,
            tenant_id=s.tenant_id,
            name=s.name,
            description=s.description,
            trigger=s.trigger,
            is_active=s.is_active,
            steps=steps_by_seq.get(s.id, []),
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in seqs
    ]


@router.post("", response_model=SequenceResponse, status_code=status.HTTP_201_CREATED)
async def create_sequence(
    payload: SequenceCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    seq = EmailSequence(
        tenant_id=current_user.tenant_id,
        name=payload.name,
        description=payload.description,
        trigger=payload.trigger,
        is_active=payload.is_active,
    )
    db.add(seq)
    await db.flush()  # Need ID for steps

    for step_input in payload.steps:
        # Verifie template appartient au tenant
        tpl_res = await db.execute(
            select(EmailTemplate).where(
                EmailTemplate.id == step_input.template_id,
                EmailTemplate.tenant_id == current_user.tenant_id,
            )
        )
        if not tpl_res.scalar_one_or_none():
            await db.rollback()
            raise HTTPException(status_code=400, detail=f"Template {step_input.template_id} invalide")
        db.add(SequenceStep(
            sequence_id=seq.id,
            template_id=step_input.template_id,
            order_index=step_input.order_index,
            delay_hours=step_input.delay_hours,
        ))

    await db.commit()
    await db.refresh(seq)
    return SequenceResponse(
        id=seq.id, tenant_id=seq.tenant_id, name=seq.name, description=seq.description,
        trigger=seq.trigger, is_active=seq.is_active, steps=[],
        created_at=seq.created_at, updated_at=seq.updated_at,
    )


@router.patch("/{sequence_id}", response_model=SequenceResponse)
async def update_sequence(
    sequence_id: UUID,
    payload: SequenceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(EmailSequence).where(
            EmailSequence.id == sequence_id,
            EmailSequence.tenant_id == current_user.tenant_id,
        )
    )
    seq = res.scalar_one_or_none()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence introuvable")
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(seq, k, v)
    seq.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(seq)
    return SequenceResponse(
        id=seq.id, tenant_id=seq.tenant_id, name=seq.name, description=seq.description,
        trigger=seq.trigger, is_active=seq.is_active, steps=[],
        created_at=seq.created_at, updated_at=seq.updated_at,
    )


@router.delete("/{sequence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sequence(
    sequence_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(EmailSequence).where(
            EmailSequence.id == sequence_id,
            EmailSequence.tenant_id == current_user.tenant_id,
        )
    )
    seq = res.scalar_one_or_none()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence introuvable")
    await db.delete(seq)
    await db.commit()


@router.post("/{sequence_id}/enroll/{candidate_id}", status_code=status.HTTP_201_CREATED)
async def enroll_candidate(
    sequence_id: UUID,
    candidate_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Enrole manuellement un candidat dans une sequence (out-of-trigger)."""
    seq_res = await db.execute(
        select(EmailSequence).where(
            EmailSequence.id == sequence_id,
            EmailSequence.tenant_id == current_user.tenant_id,
        )
    )
    seq = seq_res.scalar_one_or_none()
    if not seq:
        raise HTTPException(status_code=404, detail="Sequence introuvable")

    # Calcule next_run depuis le 1er step
    steps_res = await db.execute(
        select(SequenceStep).where(SequenceStep.sequence_id == seq.id)
        .order_by(SequenceStep.order_index)
    )
    steps = list(steps_res.scalars().all())
    if not steps:
        raise HTTPException(status_code=400, detail="Sequence sans steps")

    enrollment = SequenceEnrollment(
        tenant_id=current_user.tenant_id,
        sequence_id=seq.id,
        candidate_id=candidate_id,
        current_step_index=0,
        next_run_at=datetime.now(timezone.utc),  # 1er step immediat
        status="active",
    )
    db.add(enrollment)
    await db.commit()
    return {"enrollment_id": str(enrollment.id), "status": "active"}
