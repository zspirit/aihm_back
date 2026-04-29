import asyncio
import json
import logging
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import NotificationResponse, PaginatedNotifications
from app.services.notification_pubsub import subscribe

logger = logging.getLogger(__name__)

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


# ─── Server-Sent Events stream ─────────────────────────────────────────────────
# Push real-time des notifications via Redis pub/sub.
# Côté client : utiliser `@microsoft/fetch-event-source` (supporte Authorization
# header, contrairement à l'EventSource natif).
#
# Format SSE :
#   event: notification
#   data: {...JSON...}
#
#   :ping        ← heartbeat toutes les 15s (commentaire SSE, ignoré par client)
#
# La DB reste source de vérité : si le client manque un event (offline,
# reconnect en cours), il rattrape via GET /notifications.

_HEARTBEAT_INTERVAL_S = 15


@router.get("/stream")
async def notifications_stream(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """SSE stream — push real-time des notifications du user.

    Souscrit aux canaux Redis :
    - `notif:user:{user_id}`   → notifs personnelles
    - `notif:tenant:{tenant_id}` → broadcast tenant

    Heartbeat 15s pour éviter que les proxies coupent la connexion.
    """
    user_id = current_user.id
    tenant_id = current_user.tenant_id
    channels = [f"notif:user:{user_id}", f"notif:tenant:{tenant_id}"]

    async def event_gen():
        try:
            async with subscribe(channels) as pubsub:
                # Event 'connected' initial (utile pour le client qui veut
                # savoir qu'on est bien hooked)
                yield (
                    "event: connected\n"
                    f"data: {json.dumps({'user_id': str(user_id)})}\n\n"
                )

                last_heartbeat = time.monotonic()

                while True:
                    if await request.is_disconnected():
                        logger.info("sse_client_disconnected", user_id=str(user_id))
                        break

                    # Poll Redis avec timeout court pour pouvoir checker disconnect
                    try:
                        msg = await pubsub.get_message(
                            ignore_subscribe_messages=True, timeout=1.0
                        )
                    except Exception as exc:
                        logger.warning(
                            "sse_pubsub_get_message_error",
                            exc_info=exc,
                            user_id=str(user_id),
                        )
                        msg = None
                        await asyncio.sleep(1)

                    if msg and msg.get("type") == "message":
                        # data is already str (decode_responses=True dans le client)
                        payload_str = msg["data"]
                        if isinstance(payload_str, bytes):
                            payload_str = payload_str.decode("utf-8")
                        yield f"event: notification\ndata: {payload_str}\n\n"

                    # Heartbeat
                    now = time.monotonic()
                    if now - last_heartbeat >= _HEARTBEAT_INTERVAL_S:
                        yield ": ping\n\n"
                        last_heartbeat = now
        except asyncio.CancelledError:
            logger.info("sse_stream_cancelled", user_id=str(user_id))
            raise
        except Exception:
            logger.exception("sse_stream_unexpected_error", user_id=str(user_id))
            raise

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Désactive le buffering nginx (essentiel pour SSE en prod)
            "X-Accel-Buffering": "no",
        },
    )
