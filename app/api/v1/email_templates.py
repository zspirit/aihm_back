"""Email templates + send endpoints — Phase 2.1.

GET    /email-templates                liste
POST   /email-templates                create
GET    /email-templates/{id}           detail
PATCH  /email-templates/{id}           update
DELETE /email-templates/{id}           delete
POST   /email-templates/{id}/preview   preview avec variables sample

POST   /candidates/{cid}/send-email    envoi (template_id ou body direct)
GET    /candidates/{cid}/emails        historique d'envois
"""
from datetime import datetime, timezone
from typing import Optional, Union
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.candidate import Candidate
from app.models.email_template import EmailLog, EmailTemplate
from app.models.position import Position
from app.models.user import User
from app.schemas.email_template import (
    EmailLogResponse,
    EmailTemplateCreate,
    EmailTemplateResponse,
    EmailTemplateUpdate,
    SendEmailDirect,
    SendEmailFromTemplate,
    TemplatePreview,
)
from app.services.email_render import build_context, render_template

router = APIRouter(prefix="/email-templates", tags=["email-templates"])


# -- CRUD templates --------------------------------------------------------


@router.get("", response_model=list[EmailTemplateResponse])
async def list_templates(
    type_filter: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    q = select(EmailTemplate).where(EmailTemplate.tenant_id == current_user.tenant_id)
    if type_filter:
        q = q.where(EmailTemplate.type == type_filter)
    q = q.order_by(desc(EmailTemplate.created_at))
    res = await db.execute(q)
    return res.scalars().all()


@router.post("", response_model=EmailTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: EmailTemplateCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tpl = EmailTemplate(
        tenant_id=current_user.tenant_id,
        name=payload.name,
        type=payload.type,
        subject=payload.subject,
        body_markdown=payload.body_markdown,
        is_active=payload.is_active,
    )
    db.add(tpl)
    await db.commit()
    await db.refresh(tpl)
    return tpl


@router.get("/{template_id}", response_model=EmailTemplateResponse)
async def get_template(
    template_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tpl = await _get_template(template_id, current_user, db)
    return tpl


@router.patch("/{template_id}", response_model=EmailTemplateResponse)
async def update_template(
    template_id: UUID,
    payload: EmailTemplateUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tpl = await _get_template(template_id, current_user, db)
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(tpl, k, v)
    tpl.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(tpl)
    return tpl


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tpl = await _get_template(template_id, current_user, db)
    await db.delete(tpl)
    await db.commit()


@router.post("/{template_id}/preview", response_model=TemplatePreview)
async def preview_template(
    template_id: UUID,
    extra_variables: dict = Body(default_factory=dict),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rend le template avec un contexte sample (admin tenant + variables custom)."""
    tpl = await _get_template(template_id, current_user, db)
    ctx = build_context(
        candidate={"name": "Jean Dupont", "email": "jean@example.com", "phone": "+33612345678"},
        position={"title": "Developpeur Full Stack", "seniority_level": "senior"},
        recruiter={"name": current_user.email, "email": current_user.email},
        tenant={"name": "AIHM"},
        extra=extra_variables,
    )
    subject_r, _ = render_template(tpl.subject, ctx)
    body_r, vars_used = render_template(tpl.body_markdown, ctx)
    return TemplatePreview(
        subject=subject_r,
        body_rendered=body_r,
        variables_used=list(set(vars_used)),
    )


async def _get_template(template_id: UUID, current_user: User, db: AsyncSession) -> EmailTemplate:
    res = await db.execute(
        select(EmailTemplate).where(
            EmailTemplate.id == template_id,
            EmailTemplate.tenant_id == current_user.tenant_id,
        )
    )
    tpl = res.scalar_one_or_none()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template introuvable")
    return tpl


# -- Sending (mounted on /candidates) --------------------------------------

candidate_email_router = APIRouter(tags=["email-templates"])


SendEmailPayload = Union[SendEmailFromTemplate, SendEmailDirect]


class _PolymorphicSend(BaseModel):
    """Wrapper pour FastAPI : accepte soit template_id+extras, soit direct subject+body."""

    template_id: Optional[UUID] = None
    extra_variables: dict = {}
    to_email: Optional[str] = None
    subject: Optional[str] = None
    body_markdown: Optional[str] = None


@candidate_email_router.post(
    "/candidates/{candidate_id}/send-email",
    response_model=EmailLogResponse,
)
async def send_email_to_candidate(
    candidate_id: UUID,
    payload: _PolymorphicSend,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Envoie un email a un candidat. Soit via template, soit body direct.

    En v0.0.1 : provider='console' (logue mais ne dispatch pas reellement).
    Quand un provider SMTP/Sendgrid est configure cote env, on flippe le
    provider et on envoie reellement.
    """
    cand_res = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidate = cand_res.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    to_email = payload.to_email or candidate.email
    if not to_email:
        raise HTTPException(status_code=400, detail="Email candidat manquant")

    # Position liee si dispo
    position = None
    if candidate.position_id:
        pos_res = await db.execute(select(Position).where(Position.id == candidate.position_id))
        position = pos_res.scalar_one_or_none()

    template_obj: EmailTemplate | None = None
    subject_template = ""
    body_template = ""

    if payload.template_id:
        template_obj = await _get_template(payload.template_id, current_user, db)
        subject_template = template_obj.subject
        body_template = template_obj.body_markdown
    elif payload.subject and payload.body_markdown:
        subject_template = payload.subject
        body_template = payload.body_markdown
    else:
        raise HTTPException(status_code=400, detail="Fournir template_id OU subject+body_markdown")

    ctx = build_context(
        candidate={"name": candidate.name, "email": candidate.email, "phone": candidate.phone},
        position={"title": position.title, "seniority_level": position.seniority_level} if position else None,
        recruiter={"name": current_user.email, "email": current_user.email},
        tenant={"name": "AIHM"},
        extra=payload.extra_variables or {},
    )
    subject_r, _ = render_template(subject_template, ctx)
    body_r, _ = render_template(body_template, ctx)

    log = EmailLog(
        tenant_id=current_user.tenant_id,
        candidate_id=candidate_id,
        template_id=template_obj.id if template_obj else None,
        sent_by=current_user.id,
        to_email=to_email,
        subject=subject_r,
        body_rendered=body_r,
        variables=payload.extra_variables or None,
        status="sent",
        provider="console",
        sent_at=datetime.now(timezone.utc),
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)

    # En vrai : ici on dispatche via Celery (worker email) au provider configure
    # tenant.smtp_settings ou env SENDGRID_API_KEY. Logue console-only pour v0.0.1.

    return EmailLogResponse(
        id=log.id,
        candidate_id=log.candidate_id,
        template_id=log.template_id,
        template_name=template_obj.name if template_obj else None,
        to_email=log.to_email,
        subject=log.subject,
        body_rendered=log.body_rendered,
        status=log.status,
        provider=log.provider,
        error=log.error,
        created_at=log.created_at,
        sent_at=log.sent_at,
    )


@candidate_email_router.get(
    "/candidates/{candidate_id}/emails",
    response_model=list[EmailLogResponse],
)
async def list_candidate_emails(
    candidate_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cand_res = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    if not cand_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    res = await db.execute(
        select(EmailLog, EmailTemplate.name)
        .outerjoin(EmailTemplate, EmailTemplate.id == EmailLog.template_id)
        .where(
            EmailLog.candidate_id == candidate_id,
            EmailLog.tenant_id == current_user.tenant_id,
        )
        .order_by(desc(EmailLog.created_at))
    )
    out = []
    for log, tpl_name in res.all():
        out.append(EmailLogResponse(
            id=log.id,
            candidate_id=log.candidate_id,
            template_id=log.template_id,
            template_name=tpl_name,
            to_email=log.to_email,
            subject=log.subject,
            body_rendered=log.body_rendered,
            status=log.status,
            provider=log.provider,
            error=log.error,
            created_at=log.created_at,
            sent_at=log.sent_at,
        ))
    return out
