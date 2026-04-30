from datetime import datetime
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.tenant import Tenant
from app.models.user import User
from app.services.notification_pubsub import publish_user_sync
from app.services.slack import send_message_sync as slack_send

logger = structlog.get_logger()

# Notification types that should also fan-out to a tenant's Slack webhook
# when configured. Keep this short — Slack is a coarse channel; only push
# things a hiring team genuinely wants to see in real time.
_SLACK_FORWARD_TYPES = {
    "candidate.cv_analyzed",
    "auto_flagged_for_review",
    "interview_completed",
    "offer.signed",
}


def _slack_text_for(notif: Notification) -> str:
    """Render the one-line Slack message for a notification."""
    title = notif.title or notif.type
    if notif.message:
        return f"*{title}* — {notif.message}"
    return f"*{title}*"


def _maybe_forward_to_slack(session: Session, notif: Notification) -> None:
    """Look up the tenant's Slack webhook (if any) and forward.
    Fire-and-forget: never raises."""
    if notif.type not in _SLACK_FORWARD_TYPES:
        return
    try:
        tenant = session.get(Tenant, notif.tenant_id)
        if tenant is None:
            return
        url = (tenant.modules_config or {}).get("slack_webhook_url")
        if not url:
            return
        slack_send(url, _slack_text_for(notif))
    except Exception:
        logger.warning("notif_slack_forward_failed", exc_info=True)


def _payload_for_pubsub(notif: Notification) -> dict:
    """Sérialisation SSE-friendly d'une Notification."""
    return {
        "id": str(notif.id),
        "tenant_id": str(notif.tenant_id),
        "user_id": str(notif.user_id) if notif.user_id else None,
        "type": notif.type,
        "title": notif.title,
        "message": notif.message,
        "data": notif.data or {},
        "read": bool(notif.read) if notif.read is not None else False,
        "created_at": (notif.created_at or datetime.utcnow()).isoformat(),
    }


def create_notification(
    session: Session,
    tenant_id: UUID,
    user_id: UUID | None,
    type: str,
    title: str,
    message: str,
    data: dict | None = None,
):
    """Create a notification record + push real-time via Redis pub/sub.

    If user_id is None, notify all admins+recruiters in tenant.
    DB est la source de vérité, le pubsub est un push opportuniste.
    """
    created_notifs: list[Notification] = []

    if user_id is None:
        # Broadcast tenant : crée une notif par admin/recruteur
        result = session.execute(
            select(User).where(
                User.tenant_id == tenant_id,
                User.role.in_(["admin", "recruiter"]),
            )
        )
        users = result.scalars().all()

        for user in users:
            notification = Notification(
                tenant_id=tenant_id,
                user_id=user.id,
                type=type,
                title=title,
                message=message,
                data=data,
            )
            session.add(notification)
            created_notifs.append(notification)

        logger.info(
            "notifications_created_bulk",
            tenant_id=str(tenant_id),
            type=type,
            count=len(users),
        )
    else:
        notification = Notification(
            tenant_id=tenant_id,
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            data=data,
        )
        session.add(notification)
        created_notifs.append(notification)

        logger.info(
            "notification_created",
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            type=type,
        )

    # Flush pour avoir les IDs avant publish
    session.flush()

    # Push real-time via Redis (fire-and-forget, n'échoue jamais)
    for n in created_notifs:
        if n.user_id:
            publish_user_sync(n.user_id, _payload_for_pubsub(n))

    # Best-effort fan-out to the tenant's Slack webhook for whitelisted types.
    # Forward ONCE per tenant+type even when we created N user-rows above —
    # otherwise a 50-recruiter tenant gets 50 Slack pings per CV.
    seen_tenants: set[tuple[UUID, str]] = set()
    for n in created_notifs:
        key = (n.tenant_id, n.type)
        if key in seen_tenants:
            continue
        seen_tenants.add(key)
        _maybe_forward_to_slack(session, n)
