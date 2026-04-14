from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.candidate import Candidate
from app.models.consent import Consent
from app.models.position import Position
from app.models.user import User

router = APIRouter(tags=["candidates"])


@router.post("/candidates/{candidate_id}/invite/preview")
async def preview_invite_email(
    candidate_id: UUID,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Preview the consent invitation email before sending."""
    from app.models.tenant import Tenant
    from app.services.email import render

    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    position = None
    if candidate.position_id:
        pos_result = await db.execute(select(Position).where(Position.id == candidate.position_id))
        position = pos_result.scalar_one_or_none()

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
    tenant = tenant_result.scalar_one_or_none()

    position_title = position.title if position else "—"
    tenant_name = tenant.name if tenant else "—"
    subject = f"Entretien telephonique IA - {position_title} - {tenant_name}"

    html = render(
        "email/consent_invite.html",
        candidate_name=candidate.name,
        tenant_name=tenant_name,
        position_title=position_title,
        consent_url="{{consent_url}}",
    )

    return {
        "subject": subject,
        "html": html,
        "to": candidate.email,
        "candidate_name": candidate.name,
        "position_title": position_title,
        "tenant_name": tenant_name,
    }


@router.post("/candidates/{candidate_id}/invite")
async def invite_candidate(
    candidate_id: UUID,
    body: dict | None = None,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Send consent email to candidate and move to 'invited' status.
    Optionally accepts custom subject/html in body."""
    from app.models.tenant import Tenant

    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    if not candidate.email:
        raise HTTPException(status_code=400, detail="Le candidat n'a pas d'adresse email")

    # Create granular consent records (4 types) + legacy data_processing for backward compat
    import uuid as _uuid
    CONSENT_TYPES = ["data_processing", "scoring", "call_recording", "data_transfer_us"]

    # Check if consents already exist for this candidate
    existing_result = await db.execute(
        select(Consent).where(Consent.candidate_id == candidate_id)
    )
    existing_consents = {c.type: c for c in existing_result.scalars().all()}

    consent = None
    for consent_type in CONSENT_TYPES:
        if consent_type not in existing_consents:
            new_consent = Consent(
                candidate_id=candidate_id,
                token=str(_uuid.uuid4()),
                type=consent_type,
                granted=False,
            )
            db.add(new_consent)
            if consent_type == "data_processing":
                consent = new_consent
        else:
            if consent_type == "data_processing":
                consent = existing_consents[consent_type]
    await db.flush()

    if consent is None:
        consent = existing_consents.get("data_processing")

    custom_subject = body.get("subject") if body else None
    custom_html = body.get("html") if body else None
    scheduled_at_str = body.get("scheduled_at") if body else None

    scheduled_at = None
    if scheduled_at_str:
        from datetime import datetime, timezone
        try:
            scheduled_at = datetime.fromisoformat(scheduled_at_str.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Format de date invalide")

    if custom_subject and custom_html:
        from app.core.config import get_settings
        settings = get_settings()
        consent_url = f"{settings.FRONTEND_URL}/consent/{consent.token}"
        final_html = custom_html.replace("{{consent_url}}", consent_url)

        try:
            from app.workers.notifications import send_email
            if scheduled_at:
                send_email.apply_async(
                    args=[candidate.email, custom_subject, final_html],
                    eta=scheduled_at,
                )
            else:
                send_email.delay(candidate.email, custom_subject, final_html)
        except Exception:
            pass
        candidate.pipeline_status = "invited"
    else:
        try:
            from app.workers.notifications import send_consent_email
            if scheduled_at:
                send_consent_email.apply_async(args=[str(candidate_id)], eta=scheduled_at)
            else:
                send_consent_email.delay(str(candidate_id))
        except Exception:
            candidate.pipeline_status = "invited"

    msg = f"Invitation planifiee pour {scheduled_at.isoformat()}" if scheduled_at else "Invitation envoyee"
    return {"status": "ok", "message": msg}


@router.post("/candidates/{candidate_id}/grant-consent")
async def grant_consent_admin(
    candidate_id: UUID,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    from datetime import datetime, timezone
    import uuid as _uuid

    # Ensure all 4 consent types exist and are granted
    ALL_CONSENT_TYPES = ["data_processing", "scoring", "call_recording", "data_transfer_us"]
    for consent_type in ALL_CONSENT_TYPES:
        consent_result = await db.execute(
            select(Consent).where(
                Consent.candidate_id == candidate_id,
                Consent.type == consent_type,
            )
        )
        consent = consent_result.scalar_one_or_none()
        if not consent:
            consent = Consent(
                candidate_id=candidate_id,
                type=consent_type,
                token=str(_uuid.uuid4()),
                granted=True,
                granted_at=datetime.now(timezone.utc),
                channel="admin",
            )
            db.add(consent)
        else:
            consent.granted = True
            consent.granted_at = datetime.now(timezone.utc)
            consent.channel = "admin"

    candidate.pipeline_status = "consent_given"
    await db.commit()

    return {"status": "ok", "message": "Consentements accordés (data_processing + scoring + call_recording + data_transfer_us)"}
