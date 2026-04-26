"""Position approval workflow — Phase 1.5 V1_ROADMAP.

POST /positions/{id}/submit-for-approval  -> status=draft, workflow_status=pending_approval
                                              cree une approval_request liee
POST /positions/{id}/approve              -> approver-only, marque approved
POST /positions/{id}/publish              -> approved -> active (publication)
"""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.approval_request import ApprovalRequest
from app.models.position import Position
from app.models.user import User

router = APIRouter(prefix="/positions", tags=["positions"])


class SubmitForApproval(BaseModel):
    approver_id: UUID
    rationale: str | None = Field(None, max_length=2000)


@router.post("/{position_id}/submit-for-approval")
async def submit_for_approval(
    position_id: UUID,
    payload: SubmitForApproval = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soumet le poste pour validation. Cree une approval_request liee."""
    res = await db.execute(
        select(Position).where(
            Position.id == position_id,
            Position.tenant_id == current_user.tenant_id,
        )
    )
    pos = res.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Poste introuvable")
    if pos.workflow_status == "pending_approval":
        raise HTTPException(status_code=400, detail="Validation deja en cours")
    if pos.status == "active":
        raise HTTPException(status_code=400, detail="Poste deja actif")
    if payload.approver_id == current_user.id:
        raise HTTPException(status_code=400, detail="Auto-approval interdite")

    # Approver doit exister dans le tenant
    appr_res = await db.execute(
        select(User).where(
            User.id == payload.approver_id,
            User.tenant_id == current_user.tenant_id,
        )
    )
    if not appr_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Approver introuvable")

    # Cree approval request
    ar = ApprovalRequest(
        tenant_id=current_user.tenant_id,
        requester_id=current_user.id,
        approver_id=payload.approver_id,
        entity_type="position",
        entity_id=pos.id,
        title=f"Validation poste : {pos.title}",
        rationale=payload.rationale,
        status="pending",
    )
    db.add(ar)

    pos.workflow_status = "pending_approval"
    pos.submitted_for_approval_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(pos)

    return {
        "position_id": str(pos.id),
        "workflow_status": pos.workflow_status,
        "approval_request_id": str(ar.id),
    }


@router.post("/{position_id}/approve")
async def approve_position(
    position_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Marque la position approuvee (corollaire d'une approval decided=approved).

    Note : ce endpoint sert de raccourci pour aligner le workflow_status. Un
    user qui passe par /approvals/{id}/decide approved doit aussi appeler
    celui-ci pour finaliser la transition. UX a wirer cote frontend.
    """
    res = await db.execute(
        select(Position).where(
            Position.id == position_id,
            Position.tenant_id == current_user.tenant_id,
        )
    )
    pos = res.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Poste introuvable")
    if pos.workflow_status != "pending_approval":
        raise HTTPException(status_code=400, detail="Pas de demande en cours")

    # Verifie qu'une approval approved existe pour ce poste cote current_user
    ar_res = await db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.entity_type == "position",
            ApprovalRequest.entity_id == pos.id,
            ApprovalRequest.approver_id == current_user.id,
            ApprovalRequest.status == "approved",
        )
    )
    if not ar_res.scalar_one_or_none():
        raise HTTPException(
            status_code=403, detail="Validation requise via /approvals/{id}/decide d'abord",
        )

    pos.workflow_status = "approved"
    pos.approved_at = datetime.now(timezone.utc)
    await db.commit()
    return {"position_id": str(pos.id), "workflow_status": pos.workflow_status}


@router.post("/{position_id}/publish")
async def publish_position(
    position_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Publie un poste approuve : workflow_status=approved -> status=active.

    Si workflow_status est null (tenant n'utilise pas le workflow), passe direct.
    """
    res = await db.execute(
        select(Position).where(
            Position.id == position_id,
            Position.tenant_id == current_user.tenant_id,
        )
    )
    pos = res.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Poste introuvable")

    if pos.workflow_status not in (None, "approved"):
        raise HTTPException(
            status_code=400,
            detail=f"Publication impossible : workflow_status={pos.workflow_status}",
        )

    pos.status = "active"
    if pos.workflow_status == "approved":
        pos.workflow_status = "active"
    await db.commit()
    return {"position_id": str(pos.id), "status": pos.status}
