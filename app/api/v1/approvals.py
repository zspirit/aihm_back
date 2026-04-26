"""Endpoints approval requests — Phase 1.3 V1_ROADMAP.

POST   /approvals                          cree une demande (requester defini = current_user)
GET    /approvals                          liste : ?role=mine|approver|requester filtre
GET    /approvals/{id}                     detail
POST   /approvals/{id}/decide              approver decide (approved|rejected)
POST   /approvals/{id}/cancel              requester annule
"""
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.approval_request import ApprovalRequest
from app.models.user import User
from app.schemas.approval_request import (
    ApprovalDecision,
    ApprovalRequestCreate,
    ApprovalRequestResponse,
    UserSummary,
)

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _user_summary(u: User) -> UserSummary:
    return UserSummary(
        id=u.id,
        full_name=getattr(u, "full_name", None),
        email=u.email,
        role=u.role,
    )


def _to_response(ar: ApprovalRequest, requester: User, approver: User) -> ApprovalRequestResponse:
    return ApprovalRequestResponse(
        id=ar.id,
        tenant_id=ar.tenant_id,
        requester=_user_summary(requester),
        approver=_user_summary(approver),
        entity_type=ar.entity_type,
        entity_id=ar.entity_id,
        title=ar.title,
        rationale=ar.rationale,
        status=ar.status,
        decision_reason=ar.decision_reason,
        requested_at=ar.requested_at,
        decided_at=ar.decided_at,
    )


@router.post("", response_model=ApprovalRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_approval(
    payload: ApprovalRequestCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cree une demande d'approval. Le requester = current_user."""
    if payload.approver_id == current_user.id:
        raise HTTPException(status_code=400, detail="Auto-approval interdite")

    # Verifie que l'approver est dans le meme tenant
    approver_res = await db.execute(
        select(User).where(
            User.id == payload.approver_id,
            User.tenant_id == current_user.tenant_id,
        )
    )
    approver = approver_res.scalar_one_or_none()
    if not approver:
        raise HTTPException(status_code=404, detail="Approver introuvable dans le tenant")

    ar = ApprovalRequest(
        tenant_id=current_user.tenant_id,
        requester_id=current_user.id,
        approver_id=payload.approver_id,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        title=payload.title,
        rationale=payload.rationale,
        status="pending",
    )
    db.add(ar)
    await db.commit()
    await db.refresh(ar)
    return _to_response(ar, current_user, approver)


@router.get("", response_model=list[ApprovalRequestResponse])
async def list_approvals(
    role: Literal["mine", "approver", "requester", "all"] = Query("all"),
    status_filter: Literal["pending", "approved", "rejected", "canceled", "all"] = Query("all"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Liste les approvals visibles par current_user.

    role:
    - mine     : ou je suis approver OU requester (defaut sain pour Dashboard)
    - approver : seulement celles que je dois trancher
    - requester: seulement celles que j'ai demandees
    - all      : toutes du tenant (admin uniquement, sinon equivalent a 'mine')
    """
    if role == "all" and current_user.role != "admin":
        role = "mine"

    query = select(ApprovalRequest).where(ApprovalRequest.tenant_id == current_user.tenant_id)

    if role == "mine":
        query = query.where(
            or_(
                ApprovalRequest.requester_id == current_user.id,
                ApprovalRequest.approver_id == current_user.id,
            )
        )
    elif role == "approver":
        query = query.where(ApprovalRequest.approver_id == current_user.id)
    elif role == "requester":
        query = query.where(ApprovalRequest.requester_id == current_user.id)

    if status_filter != "all":
        query = query.where(ApprovalRequest.status == status_filter)

    query = query.order_by(desc(ApprovalRequest.requested_at))
    res = await db.execute(query)
    items = res.scalars().all()

    if not items:
        return []

    # Charge les users (requester + approver) en bulk
    user_ids = set()
    for ar in items:
        user_ids.add(ar.requester_id)
        user_ids.add(ar.approver_id)
    users_res = await db.execute(select(User).where(User.id.in_(user_ids)))
    users_by_id = {u.id: u for u in users_res.scalars().all()}

    return [
        _to_response(ar, users_by_id[ar.requester_id], users_by_id[ar.approver_id])
        for ar in items
    ]


@router.get("/{approval_id}", response_model=ApprovalRequestResponse)
async def get_approval(
    approval_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Detail d'une approval (visible par requester, approver, ou admin tenant)."""
    ar_res = await db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.tenant_id == current_user.tenant_id,
        )
    )
    ar = ar_res.scalar_one_or_none()
    if not ar:
        raise HTTPException(status_code=404, detail="Approval introuvable")
    if (
        ar.requester_id != current_user.id
        and ar.approver_id != current_user.id
        and current_user.role != "admin"
    ):
        raise HTTPException(status_code=403, detail="Lecture non autorisee")

    requester_res = await db.execute(select(User).where(User.id == ar.requester_id))
    requester = requester_res.scalar_one()
    approver_res = await db.execute(select(User).where(User.id == ar.approver_id))
    approver = approver_res.scalar_one()
    return _to_response(ar, requester, approver)


@router.post("/{approval_id}/decide", response_model=ApprovalRequestResponse)
async def decide_approval(
    approval_id: UUID,
    payload: ApprovalDecision,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Approver tranche : approved | rejected. Idempotent si meme decision."""
    ar_res = await db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.tenant_id == current_user.tenant_id,
        )
    )
    ar = ar_res.scalar_one_or_none()
    if not ar:
        raise HTTPException(status_code=404, detail="Approval introuvable")
    if ar.approver_id != current_user.id:
        raise HTTPException(status_code=403, detail="Vous n'etes pas l'approver")
    if ar.status not in ("pending",):
        raise HTTPException(
            status_code=400, detail=f"Approval deja decidee ({ar.status})"
        )

    ar.status = payload.decision
    ar.decision_reason = payload.decision_reason
    ar.decided_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(ar)

    requester_res = await db.execute(select(User).where(User.id == ar.requester_id))
    return _to_response(ar, requester_res.scalar_one(), current_user)


@router.post("/{approval_id}/cancel", response_model=ApprovalRequestResponse)
async def cancel_approval(
    approval_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Requester annule une approval qu'il a creee (uniquement si encore pending)."""
    ar_res = await db.execute(
        select(ApprovalRequest).where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.tenant_id == current_user.tenant_id,
        )
    )
    ar = ar_res.scalar_one_or_none()
    if not ar:
        raise HTTPException(status_code=404, detail="Approval introuvable")
    if ar.requester_id != current_user.id:
        raise HTTPException(status_code=403, detail="Vous n'etes pas le requester")
    if ar.status != "pending":
        raise HTTPException(
            status_code=400, detail=f"Approval deja decidee ({ar.status})"
        )

    ar.status = "canceled"
    ar.decided_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(ar)

    approver_res = await db.execute(select(User).where(User.id == ar.approver_id))
    return _to_response(ar, current_user, approver_res.scalar_one())
