from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.user import User

logger = structlog.get_logger()


def create_notification(
    session: Session,
    tenant_id: UUID,
    user_id: UUID | None,
    type: str,
    title: str,
    message: str,
    data: dict | None = None,
):
    """
    Create a notification record.
    If user_id is None, notify all admins+recruiters in tenant.
    """
    if user_id is None:
        # Notify all admins and recruiters in tenant
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

        logger.info(
            "notification_created",
            tenant_id=str(tenant_id),
            user_id=str(user_id),
            type=type,
        )

    session.flush()
