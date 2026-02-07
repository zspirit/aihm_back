import structlog
from celery import shared_task

logger = structlog.get_logger()


@shared_task(name="notifications.send_email")
def send_email(to: str, subject: str, html_body: str):
    logger.info("send_email", to=to, subject=subject)

    from app.core.config import get_settings

    settings = get_settings()

    if not settings.RESEND_API_KEY:
        logger.warning("email_skip_no_api_key", to=to)
        return {"status": "skipped", "reason": "no_api_key"}

    try:
        import httpx

        response = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            json={
                "from": settings.EMAIL_FROM,
                "to": [to],
                "subject": subject,
                "html": html_body,
            },
        )
        response.raise_for_status()
        logger.info("email_sent", to=to)
        return {"status": "sent"}
    except Exception as e:
        logger.error("email_error", to=to, error=str(e))
        return {"status": "error", "error": str(e)}


@shared_task(name="notifications.send_consent_email")
def send_consent_email(candidate_id: str):
    from app.workers.cv_processing import get_sync_session

    session = get_sync_session()
    try:
        from uuid import UUID

        from sqlalchemy import select

        from app.core.config import get_settings
        from app.models.candidate import Candidate
        from app.models.consent import Consent
        from app.models.position import Position
        from app.models.tenant import Tenant

        settings = get_settings()
        candidate = session.get(Candidate, UUID(candidate_id))
        if not candidate or not candidate.email:
            return

        position = session.get(Position, candidate.position_id)
        tenant = session.get(Tenant, candidate.tenant_id)

        consent_result = session.execute(
            select(Consent).where(
                Consent.candidate_id == candidate.id,
                Consent.type == "data_processing",
            )
        )
        consent = consent_result.scalar_one_or_none()
        if not consent:
            return

        consent_url = f"{settings.FRONTEND_URL}/consent/{consent.token}"

        html = f"""
        <h2>Invitation a un entretien telephonique IA</h2>
        <p>Bonjour {candidate.name},</p>
        <p>{tenant.name} souhaite vous proposer un entretien telephonique assiste par IA
        pour le poste de <strong>{position.title}</strong>.</p>
        <p>L'entretien dure environ 5 minutes. Un assistant IA vous posera quelques questions
        sur votre parcours et vos competences. L'appel sera enregistre pour analyse.</p>
        <p>Pour accepter et planifier votre entretien, cliquez sur le lien ci-dessous :</p>
        <p><a href="{consent_url}" style="background:#2563eb;color:white;padding:12px 24px;
        text-decoration:none;border-radius:6px;">Accepter et planifier</a></p>
        <p>Vous pouvez refuser a tout moment. Vos donnees sont traitees conformement
        a la loi 09-08 relative a la protection des donnees personnelles.</p>
        <p>Cordialement,<br>{tenant.name}</p>
        """

        send_email.delay(
            candidate.email,
            f"Entretien telephonique IA - {position.title} - {tenant.name}",
            html,
        )

        candidate.pipeline_status = "invited"
        session.commit()
        logger.info("consent_email_sent", candidate_id=candidate_id, to=candidate.email)

    finally:
        session.close()
