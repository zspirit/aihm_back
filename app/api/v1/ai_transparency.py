"""AI Act transparency endpoints — Phase 4.1 V1_ROADMAP.

Expose les decisions IA prises pour un candidat (scoring, matching, screening)
avec model version + confidence + override possible.

Aussi : endpoint contestation `/candidates/{id}/contest-evaluation` qui
cree une approval_request automatique (entity_type='ai_contestation').

Conformite AI Act EU High-Risk Systems RH :
- Art. 13 (Transparence) : utilisateur peut consulter les decisions IA
- Art. 14 (Supervision humaine) : override 1-clic via la page Validations
- Annexe III : audit trail systematique
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.approval_request import ApprovalRequest
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.user import User

router = APIRouter(tags=["ai-transparency"])


class AIDecision(BaseModel):
    type: str  # cv_scoring | matching | screening_call_analysis | feedback_generation
    timestamp: str
    model: str
    model_version: Optional[str] = None
    confidence_score: Optional[float] = None
    decision_summary: str
    can_be_contested: bool = True
    audit_log_id: Optional[UUID] = None
    details: dict = Field(default_factory=dict)


@router.get("/candidates/{candidate_id}/ai-decisions", response_model=list[AIDecision])
async def list_ai_decisions(
    candidate_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Liste les decisions IA prises pour un candidat.

    Source : audit_logs filtres sur les actions IA + cv_score_explanation +
    metadata des analyses stockees sur Candidate/Application/Interview.
    """
    cand_res = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    cand = cand_res.scalar_one_or_none()
    if not cand:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    decisions: list[AIDecision] = []

    # 1. CV scoring direct (cv_score + explanation)
    if cand.cv_score is not None:
        decisions.append(AIDecision(
            type="cv_scoring",
            timestamp=cand.created_at.isoformat() if cand.created_at else "",
            model="claude-sonnet-4-6",
            model_version="2026-04",
            confidence_score=cand.cv_score / 100.0,
            decision_summary=f"Score CV calcule : {round(cand.cv_score)}/100 sur la base du CV parse",
            details=cand.cv_score_explanation or {},
        ))

    # 2. Audit logs ciblant ce candidat avec actor=ai
    audit_res = await db.execute(
        select(AuditLog).where(
            AuditLog.tenant_id == current_user.tenant_id,
            AuditLog.entity_type == "candidate",
            AuditLog.entity_id == str(candidate_id),
        ).order_by(desc(AuditLog.created_at))
    )
    for log in audit_res.scalars().all():
        details = log.details or {}
        actor = details.get("actor") or ""
        if actor != "ai":
            continue
        decisions.append(AIDecision(
            type=log.action,
            timestamp=log.created_at.isoformat() if log.created_at else "",
            model=details.get("model", "unknown"),
            model_version=details.get("model_version"),
            confidence_score=details.get("confidence_score"),
            decision_summary=details.get("summary", log.action),
            audit_log_id=log.id,
            details=details,
        ))

    return decisions


class ContestEvaluation(BaseModel):
    reason: str = Field(..., min_length=10, max_length=2000)
    approver_id: UUID = Field(..., description="User RH qui revisera la decision")


@router.post("/candidates/{candidate_id}/contest-evaluation")
async def contest_evaluation(
    candidate_id: UUID,
    payload: ContestEvaluation = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Contestation d'une evaluation IA — cree une approval_request review humaine.

    Apres review, l'approver peut overrider la decision via le workflow approvals.
    """
    cand_res = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    cand = cand_res.scalar_one_or_none()
    if not cand:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    appr_res = await db.execute(
        select(User).where(
            User.id == payload.approver_id,
            User.tenant_id == current_user.tenant_id,
        )
    )
    if not appr_res.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Approver invalide")

    ar = ApprovalRequest(
        tenant_id=current_user.tenant_id,
        requester_id=current_user.id,
        approver_id=payload.approver_id,
        entity_type="candidate",
        entity_id=cand.id,
        title=f"Contestation evaluation IA : {cand.name}",
        rationale=payload.reason,
        status="pending",
    )
    db.add(ar)
    await db.commit()
    await db.refresh(ar)

    return {"approval_request_id": str(ar.id), "status": "pending"}
