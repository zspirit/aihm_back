"""CRUD for webhook subscriptions (admin only)."""

import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.user import User
from app.models.webhook_subscription import WebhookSubscription
from app.services.webhooks import WEBHOOK_EVENTS

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookCreate(BaseModel):
    url: HttpUrl
    events: list[str]


class WebhookOut(BaseModel):
    id: str
    url: str
    events: list[str]
    secret: str
    is_active: bool
    created_at: str


@router.get("")
async def list_webhooks(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WebhookSubscription)
        .where(WebhookSubscription.tenant_id == current_user.tenant_id)
        .order_by(WebhookSubscription.created_at.desc())
    )
    return [
        {
            "id": str(w.id),
            "url": w.url,
            "events": w.events,
            "secret": w.secret[:8] + "...",
            "is_active": w.is_active,
            "created_at": w.created_at.isoformat(),
        }
        for w in result.scalars().all()
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_webhook(
    body: WebhookCreate,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    invalid = [e for e in body.events if e not in WEBHOOK_EVENTS]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Evenements invalides: {invalid}. Valides: {WEBHOOK_EVENTS}",
        )

    secret = secrets.token_hex(32)
    sub = WebhookSubscription(
        tenant_id=current_user.tenant_id,
        url=str(body.url),
        secret=secret,
        events=body.events,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)

    return {
        "id": str(sub.id),
        "url": sub.url,
        "events": sub.events,
        "secret": secret,
        "is_active": sub.is_active,
        "created_at": sub.created_at.isoformat(),
    }


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: UUID,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WebhookSubscription).where(
            WebhookSubscription.id == webhook_id,
            WebhookSubscription.tenant_id == current_user.tenant_id,
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Webhook introuvable")
    await db.delete(sub)
    await db.commit()


@router.patch("/{webhook_id}/toggle")
async def toggle_webhook(
    webhook_id: UUID,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(WebhookSubscription).where(
            WebhookSubscription.id == webhook_id,
            WebhookSubscription.tenant_id == current_user.tenant_id,
        )
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=404, detail="Webhook introuvable")
    sub.is_active = not sub.is_active
    await db.commit()
    return {"id": str(sub.id), "is_active": sub.is_active}


@router.get("/events")
async def list_events(
    _: User = Depends(require_role("admin")),
):
    return WEBHOOK_EVENTS
