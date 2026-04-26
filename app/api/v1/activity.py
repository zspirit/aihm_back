"""Activity feed equipe — Phase 1.4 V1_ROADMAP.

Endpoint unifie qui aggrege les sources d'activite du tenant :
- audit_logs       (actions sur entites)
- candidate_comments  (commentaires postes)
- approval_requests  (demandes + decisions)

Retour : flux chronologique avec discriminator `type` permettant a l'UI
de rendre chaque event en bloc adapte (icone, libelle, deeplink).

GET /activity?limit=50&types=audit,comment,approval
"""
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.approval_request import ApprovalRequest
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.candidate_comment import CandidateComment
from app.models.user import User

router = APIRouter(prefix="/activity", tags=["activity"])


class ActivityActor(BaseModel):
    id: Optional[UUID] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None


class ActivityEvent(BaseModel):
    """Event unifie tous types confondus."""

    type: Literal["audit", "comment", "approval"]
    id: UUID
    timestamp: datetime
    actor: ActivityActor
    # Entite reliee (candidat, poste, offre...) — decoupage standard
    entity_type: Optional[str] = None
    entity_id: Optional[UUID] = None
    entity_label: Optional[str] = None  # Nom convivial si disponible (candidate.name, position.title)
    # Verbe / etat
    action: str
    # Champs libres : contenu commentaire, raison decision, details audit
    details: dict = Field(default_factory=dict)


@router.get("", response_model=list[ActivityEvent])
async def list_activity(
    limit: int = Query(50, ge=1, le=200),
    types: str = Query("audit,comment,approval", description="CSV des types a inclure"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retourne le flux d'activite tenant-wide ordonne par timestamp DESC.

    Pas de pagination cursor v1 — limite simple. A passer en cursor si > 200.
    """
    enabled = {t.strip() for t in types.split(",") if t.strip()}
    events: list[ActivityEvent] = []

    # --- Bulk load users + candidates pour resoudre labels ---
    user_ids: set[UUID] = set()
    cand_ids: set[UUID] = set()

    audit_rows: list[AuditLog] = []
    comment_rows: list[tuple[CandidateComment, Candidate]] = []
    approval_rows: list[ApprovalRequest] = []

    if "audit" in enabled:
        res = await db.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id == current_user.tenant_id)
            .order_by(desc(AuditLog.created_at))
            .limit(limit)
        )
        audit_rows = list(res.scalars().all())
        for r in audit_rows:
            if r.user_id:
                user_ids.add(r.user_id)
            if r.entity_type == "candidate" and r.entity_id:
                try:
                    cand_ids.add(UUID(r.entity_id))
                except (ValueError, TypeError):
                    pass

    if "comment" in enabled:
        res = await db.execute(
            select(CandidateComment, Candidate)
            .join(Candidate, Candidate.id == CandidateComment.candidate_id)
            .where(
                CandidateComment.tenant_id == current_user.tenant_id,
                CandidateComment.deleted_at.is_(None),
            )
            .order_by(desc(CandidateComment.created_at))
            .limit(limit)
        )
        comment_rows = [(c, cand) for c, cand in res.all()]
        for c, _cand in comment_rows:
            user_ids.add(c.author_id)

    if "approval" in enabled:
        res = await db.execute(
            select(ApprovalRequest)
            .where(ApprovalRequest.tenant_id == current_user.tenant_id)
            .order_by(desc(ApprovalRequest.requested_at))
            .limit(limit)
        )
        approval_rows = list(res.scalars().all())
        for r in approval_rows:
            user_ids.add(r.requester_id)
            user_ids.add(r.approver_id)

    # Resolve users en bulk
    users_by_id: dict[UUID, User] = {}
    if user_ids:
        u_res = await db.execute(select(User).where(User.id.in_(user_ids)))
        users_by_id = {u.id: u for u in u_res.scalars().all()}

    # Resolve candidates names (pour les actions audit qui ciblent un candidate
    # mais aussi pour l'enrichissement des comments)
    cand_ids.update(c.candidate_id for c, _ in comment_rows)
    cands_by_id: dict[UUID, Candidate] = {}
    if cand_ids:
        c_res = await db.execute(select(Candidate).where(Candidate.id.in_(cand_ids)))
        cands_by_id = {c.id: c for c in c_res.scalars().all()}

    def actor_from(uid: UUID | None) -> ActivityActor:
        if not uid:
            return ActivityActor()
        u = users_by_id.get(uid)
        if not u:
            return ActivityActor(id=uid)
        return ActivityActor(
            id=u.id,
            full_name=getattr(u, "full_name", None),
            email=u.email,
            role=u.role,
        )

    # --- Build events ---
    for r in audit_rows:
        entity_label = None
        entity_uuid: UUID | None = None
        if r.entity_id:
            try:
                entity_uuid = UUID(r.entity_id)
                if r.entity_type == "candidate":
                    cand = cands_by_id.get(entity_uuid)
                    if cand:
                        entity_label = cand.name
            except (ValueError, TypeError):
                pass
        events.append(
            ActivityEvent(
                type="audit",
                id=r.id,
                timestamp=r.created_at,
                actor=actor_from(r.user_id),
                entity_type=r.entity_type,
                entity_id=entity_uuid,
                entity_label=entity_label,
                action=r.action,
                details=r.details or {},
            )
        )

    for c, cand in comment_rows:
        events.append(
            ActivityEvent(
                type="comment",
                id=c.id,
                timestamp=c.created_at,
                actor=actor_from(c.author_id),
                entity_type="candidate",
                entity_id=cand.id,
                entity_label=cand.name,
                action="comment",
                details={
                    "preview": c.content[:200] + ("..." if len(c.content) > 200 else ""),
                    "is_reply": c.parent_id is not None,
                    "mentions_count": len(c.mentioned_user_ids or []),
                },
            )
        )

    for ar in approval_rows:
        # On separe en 2 events : la creation (status=pending) et la decision si decided_at
        events.append(
            ActivityEvent(
                type="approval",
                id=ar.id,
                timestamp=ar.requested_at,
                actor=actor_from(ar.requester_id),
                entity_type=ar.entity_type,
                entity_id=ar.entity_id,
                entity_label=ar.title,
                action="approval_requested",
                details={
                    "approver_id": str(ar.approver_id),
                    "approver_name": (users_by_id.get(ar.approver_id).email
                                      if users_by_id.get(ar.approver_id) else None),
                    "rationale": ar.rationale,
                    "current_status": ar.status,
                },
            )
        )
        if ar.decided_at and ar.status in ("approved", "rejected", "canceled"):
            decider = ar.requester_id if ar.status == "canceled" else ar.approver_id
            events.append(
                ActivityEvent(
                    type="approval",
                    id=ar.id,
                    timestamp=ar.decided_at,
                    actor=actor_from(decider),
                    entity_type=ar.entity_type,
                    entity_id=ar.entity_id,
                    entity_label=ar.title,
                    action=f"approval_{ar.status}",
                    details={
                        "decision_reason": ar.decision_reason,
                    },
                )
            )

    # Trie chrono DESC + cap au limit final
    events.sort(key=lambda e: e.timestamp, reverse=True)
    return events[:limit]
