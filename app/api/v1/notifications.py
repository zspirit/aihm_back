from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import NotificationResponse, PaginatedNotifications

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=PaginatedNotifications)
async def list_notifications(
    read: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List notifications for current user with pagination.
    """
    query = select(Notification).where(
        Notification.user_id == current_user.id,
        Notification.tenant_id == current_user.tenant_id,
    )
    count_query = select(func.count()).select_from(Notification).where(
        Notification.user_id == current_user.id,
        Notification.tenant_id == current_user.tenant_id,
    )

    if read is not None:
        query = query.where(Notification.read == read)
        count_query = count_query.where(Notification.read == read)

    total = (await db.execute(count_query)).scalar()

    # Get unread count
    unread_count_query = select(func.count()).select_from(Notification).where(
        Notification.user_id == current_user.id,
        Notification.tenant_id == current_user.tenant_id,
        Notification.read == False,
    )
    unread_count = (await db.execute(unread_count_query)).scalar()

    query = query.order_by(Notification.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    notifications = result.scalars().all()

    responses = [
        NotificationResponse(
            id=str(n.id),
            type=n.type,
            title=n.title,
            message=n.message,
            data=n.data,
            read=n.read,
            created_at=n.created_at,
        )
        for n in notifications
    ]

    return PaginatedNotifications(
        items=responses,
        total=total,
        unread_count=unread_count,
        page=page,
        page_size=page_size,
    )


@router.patch("/{notification_id}/read")
async def mark_notification_read(
    notification_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark a single notification as read.
    """
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
            Notification.tenant_id == current_user.tenant_id,
        )
    )
    notification = result.scalar_one_or_none()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification introuvable")

    notification.read = True
    await db.flush()

    return {"status": "ok"}


@router.patch("/read-all")
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Mark all unread notifications as read for current user.
    """
    stmt = (
        update(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.tenant_id == current_user.tenant_id,
            Notification.read == False,
        )
        .values(read=True)
    )

    result = await db.execute(stmt)
    count = result.rowcount
    await db.flush()

    return {"status": "ok", "count": count}
