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


@shared_task(name="notifications.send_sms")
def send_sms(to: str, body: str):
    logger.info("send_sms", to=to)

    from app.core.config import get_settings

    settings = get_settings()

    if not settings.TWILIO_ACCOUNT_SID or not settings.TWILIO_AUTH_TOKEN:
        logger.warning("sms_skip_no_credentials", to=to)
        return {"status": "skipped", "reason": "no_credentials"}

    try:
        from twilio.rest import Client

        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            body=body,
            from_=settings.TWILIO_PHONE_NUMBER,
            to=to,
        )
        logger.info("sms_sent", to=to, sid=message.sid)
        return {"status": "sent", "sid": message.sid}
    except Exception as e:
        logger.error("sms_error", to=to, error=str(e))
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
        from app.services.email import render

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

        html = render(
            "email/consent_invite.html",
            candidate_name=candidate.name,
            tenant_name=tenant.name,
            position_title=position.title,
            consent_url=consent_url,
        )

        send_email.delay(
            candidate.email,
            f"Entretien telephonique IA - {position.title} - {tenant.name}",
            html,
        )

        # SMS reminder if phone number available
        if candidate.phone:
            sms_body = (
                f"{tenant.name} vous invite a un entretien IA "
                f"pour le poste {position.title}. "
                f"Acceptez ici : {consent_url}"
            )
            send_sms.delay(candidate.phone, sms_body)

        candidate.pipeline_status = "invited"
        session.commit()
        logger.info("consent_email_sent", candidate_id=candidate_id, to=candidate.email)

    finally:
        session.close()


@shared_task(name="notifications.send_consent_reminder")
def send_consent_reminder(candidate_id: str):
    """Send a reminder email/SMS to candidates who haven't consented yet."""
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
        from app.services.email import render

        settings = get_settings()
        candidate = session.get(Candidate, UUID(candidate_id))
        if not candidate or not candidate.email:
            return

        # Skip if already consented
        consent_result = session.execute(
            select(Consent).where(
                Consent.candidate_id == candidate.id,
                Consent.type == "data_processing",
                Consent.granted.is_(True),
            )
        )
        if consent_result.scalar_one_or_none():
            return

        consent_result2 = session.execute(
            select(Consent).where(
                Consent.candidate_id == candidate.id,
                Consent.type == "data_processing",
            )
        )
        consent = consent_result2.scalar_one_or_none()
        if not consent:
            return

        position = session.get(Position, candidate.position_id)
        tenant = session.get(Tenant, candidate.tenant_id)
        consent_url = f"{settings.FRONTEND_URL}/consent/{consent.token}"

        html = render(
            "email/consent_reminder.html",
            candidate_name=candidate.name,
            tenant_name=tenant.name,
            position_title=position.title,
            consent_url=consent_url,
        )

        send_email.delay(
            candidate.email,
            f"Rappel : Votre entretien avec {tenant.name}",
            html,
        )

        if candidate.phone:
            send_sms.delay(
                candidate.phone,
                f"Rappel {tenant.name}: acceptez votre entretien IA pour {position.title} → {consent_url}",
            )

        logger.info("consent_reminder_sent", candidate_id=candidate_id)

    finally:
        session.close()


@shared_task(name="notifications.send_report_ready")
def send_report_ready(interview_id: str):
    """Send email to all admin/recruiter users in tenant when report is ready."""
    from app.workers.cv_processing import get_sync_session

    session = get_sync_session()
    try:
        from uuid import UUID

        from sqlalchemy import select

        from app.core.config import get_settings
        from app.models.candidate import Candidate
        from app.models.interview import Interview
        from app.models.notification import Notification
        from app.models.position import Position
        from app.models.report import Report
        from app.models.tenant import Tenant
        from app.models.user import User
        from app.services.email import render

        settings = get_settings()
        interview = session.get(Interview, UUID(interview_id))
        if not interview:
            logger.warning("report_ready_no_interview", interview_id=interview_id)
            return

        candidate = session.get(Candidate, interview.candidate_id)
        if not candidate:
            return

        position = session.get(Position, interview.position_id)
        tenant = session.get(Tenant, interview.tenant_id)

        # Get global score from report content if available
        report_result = session.execute(
            select(Report).where(Report.interview_id == interview.id)
        )
        report = report_result.scalar_one_or_none()
        global_score = None
        if report and report.content and isinstance(report.content, dict):
            global_score = report.content.get("global_score")

        # Build report URL
        report_url = f"{settings.FRONTEND_URL}/candidates/{candidate.id}"

        # Find all admin/recruiter users in tenant
        users_result = session.execute(
            select(User).where(
                User.tenant_id == interview.tenant_id,
                User.role.in_(["admin", "recruiter"]),
            )
        )
        users = users_result.scalars().all()

        for user in users:
            # Render email
            html = render(
                "email/report_ready.html",
                user_name=user.full_name,
                candidate_name=candidate.name,
                position_title=position.title,
                tenant_name=tenant.name,
                global_score=global_score,
                report_url=report_url,
            )

            send_email.delay(
                user.email,
                f"Rapport d'evaluation disponible — {candidate.name}",
                html,
            )

            # Create in-app notification
            notification = Notification(
                tenant_id=interview.tenant_id,
                user_id=user.id,
                type="report_ready",
                title="Rapport disponible",
                message=f"Le rapport d'evaluation de {candidate.name} pour {position.title} est pret.",
                data={
                    "interview_id": str(interview.id),
                    "candidate_id": str(candidate.id),
                    "position_id": str(position.id),
                    "global_score": global_score,
                },
            )
            session.add(notification)

        session.commit()
        logger.info(
            "report_ready_notifications_sent",
            interview_id=interview_id,
            user_count=len(users),
        )

    finally:
        session.close()


@shared_task(name="notifications.send_interview_complete")
def send_interview_complete(interview_id: str):
    """Notify candidate that their interview is complete."""
    from app.workers.cv_processing import get_sync_session

    session = get_sync_session()
    try:
        from uuid import UUID

        from app.models.candidate import Candidate
        from app.models.interview import Interview
        from app.models.position import Position
        from app.models.tenant import Tenant
        from app.services.email import render

        interview = session.get(Interview, UUID(interview_id))
        if not interview:
            return

        candidate = session.get(Candidate, interview.candidate_id)
        if not candidate or not candidate.email:
            return

        position = session.get(Position, interview.position_id)
        tenant = session.get(Tenant, interview.tenant_id)

        duration_s = interview.duration_seconds or 0
        minutes = duration_s // 60
        seconds = duration_s % 60
        duration = f"{minutes} min {seconds:02d} s"

        html = render(
            "email/interview_complete.html",
            candidate_name=candidate.name,
            tenant_name=tenant.name,
            position_title=position.title,
            duration=duration,
        )

        send_email.delay(
            candidate.email,
            f"Entretien termine - {position.title} - {tenant.name}",
            html,
        )

        logger.info("interview_complete_email_sent", interview_id=interview_id)

    finally:
        session.close()
