"""Public AI Act transparency endpoints — no auth, accessed via consent token.

COMP-04 + COMP-05 implementation. Lets a candidate (who has NO user account
in this system) consult the AI decisions made about them and submit a written
request for human re-examination.

Token reuse: we reuse the existing `Consent.token` issued at invite time.
The candidate already received this token in the consent email, so they can
keep it as their proof of access. No new token table needed.

Endpoints:
  GET  /public/explanation/{token}              → list of AI decisions made
  POST /public/explanation/{token}/request      → human-explanation request

Compliance:
- EU AI Act Art. 86 — right to obtain a clear and meaningful explanation
- GDPR Art. 22 — right not to be subject to a solely automated decision
- GDPR Art. 15 — right of access
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.consent import Consent
from app.services.audit import log_action

router = APIRouter(tags=["ai-transparency-public"])


class PublicAIDecision(BaseModel):
    """Public-safe shape — strips internal IDs & prompt_hash that aren't
    useful (or that we don't want to expose) to the candidate."""

    type: str
    timestamp: str
    model_family: str
    decision_summary: str
    confidence_score: float | None = None


class PublicExplanationResponse(BaseModel):
    candidate_name: str
    position_title: str | None
    pipeline_status: str | None
    decisions: list[PublicAIDecision]
    can_request_human_review: bool = True


async def _candidate_from_token(token: str, db: AsyncSession) -> Candidate:
    res = await db.execute(select(Consent).where(Consent.token == token))
    consent = res.scalar_one_or_none()
    if not consent:
        raise HTTPException(status_code=404, detail="Lien invalide ou expiré")
    cand_res = await db.execute(select(Candidate).where(Candidate.id == consent.candidate_id))
    cand = cand_res.scalar_one_or_none()
    if not cand:
        raise HTTPException(status_code=404, detail="Candidat introuvable")
    return cand


@router.get("/public/explanation/{token}", response_model=PublicExplanationResponse)
async def public_explanation(token: str, db: AsyncSession = Depends(get_db)):
    """Public read-only view of all AI decisions made about a candidate.

    Filtered to actor='ai' audit log entries — manual recruiter actions stay
    private. We strip the prompt_hash and internal audit_log_id from the
    response: the candidate doesn't need them to understand the decision.
    """
    cand = await _candidate_from_token(token, db)

    decisions: list[PublicAIDecision] = []
    # Direct CV score (pre-audit-log historic data)
    if cand.cv_score is not None and cand.created_at:
        decisions.append(PublicAIDecision(
            type="cv_scoring",
            timestamp=cand.created_at.isoformat(),
            model_family="Claude Sonnet",
            decision_summary=(
                f"Évaluation automatisée de votre CV par rapport au poste. "
                f"Score : {round(cand.cv_score)}/100."
            ),
            confidence_score=cand.cv_score / 100.0,
        ))

    # Audit-logged AI actions
    audit_res = await db.execute(
        select(AuditLog).where(
            AuditLog.entity_type == "candidate",
            AuditLog.entity_id == str(cand.id),
        ).order_by(desc(AuditLog.created_at))
    )
    for log in audit_res.scalars().all():
        details = log.details or {}
        if details.get("actor") != "ai":
            continue
        model = details.get("model", "")
        family = "Claude" if "claude" in model.lower() else (
            "Whisper" if "whisper" in model.lower() else model or "IA"
        )
        decisions.append(PublicAIDecision(
            type=log.action,
            timestamp=log.created_at.isoformat() if log.created_at else "",
            model_family=family,
            decision_summary=details.get("summary") or log.action,
            confidence_score=details.get("confidence_score"),
        ))

    position_title = None
    if cand.position_id:
        from app.models.position import Position
        pos_res = await db.execute(select(Position).where(Position.id == cand.position_id))
        pos = pos_res.scalar_one_or_none()
        position_title = pos.title if pos else None

    return PublicExplanationResponse(
        candidate_name=cand.name,
        position_title=position_title,
        pipeline_status=cand.pipeline_status,
        decisions=decisions,
    )


class ExplanationRequest(BaseModel):
    reason: str = Field(..., min_length=10, max_length=4000,
                        description="Pourquoi vous demandez une explication / revue humaine")
    contact_email: str | None = Field(None, max_length=320)


@router.post("/public/explanation/{token}/request")
async def request_human_explanation(
    token: str,
    payload: ExplanationRequest = Body(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """Candidate submits a written explanation/review request (Art. 86).

    Creates an audit log entry the tenant DPO sees in their activity feed,
    plus a notification. We don't auto-revert the decision — the human team
    must respond within 30 days (RGPD requirement).
    """
    cand = await _candidate_from_token(token, db)

    client_ip = request.client.host if request and request.client else None
    await log_action(
        db,
        tenant_id=cand.tenant_id,
        user_id=None,
        action="candidate_requested_explanation",
        entity_type="candidate",
        entity_id=str(cand.id),
        details={
            "actor": "candidate",
            "reason": payload.reason,
            "contact_email": payload.contact_email or cand.email,
            "client_ip": client_ip,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "regulation": "EU_AI_ACT_ART_86 + GDPR_ART_22",
            "due_within_days": 30,
        },
    )

    # Best-effort notification to tenant — never blocks the candidate.
    try:
        from app.services.notification_service import create_notification
        create_notification(
            session=db,
            tenant_id=cand.tenant_id,
            user_id=None,
            type="candidate_explanation_requested",
            title="Demande d'explication d'un candidat",
            message=(
                f"{cand.name} demande une explication / revue humaine "
                f"de la décision IA. À traiter sous 30 jours."
            ),
            data={"candidate_id": str(cand.id), "via": "public_explanation_form"},
        )
    except Exception:  # noqa: BLE001 - notification is best-effort
        pass

    await db.commit()
    return {"status": "received", "due_within_days": 30}


def build_explanation_url(frontend_url: str, token: str) -> str:
    """Helper for downstream email templates (COMP-05).

    The rejection email — once that pipeline is wired — should include this
    link so candidates can exercise their right to explanation directly from
    the message that informs them of the decision.
    """
    base = frontend_url.rstrip("/")
    return f"{base}/explanation/{token}"
