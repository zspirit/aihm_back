"""Webhook dispatch service — sends signed payloads to subscriber URLs."""

import hashlib
import hmac
import json
from datetime import datetime, timezone
from uuid import UUID

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.webhook_subscription import WebhookSubscription

logger = structlog.get_logger()

WEBHOOK_EVENTS = [
    "consent.given",
    "interview.completed",
    "report.ready",
    "cv.scored",
]


def _sign_payload(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


async def dispatch_event(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    event: str,
    data: dict,
) -> int:
    """Send webhook to all active subscribers for this event.

    Returns the number of successful deliveries.
    """
    result = await db.execute(
        select(WebhookSubscription).where(
            WebhookSubscription.tenant_id == tenant_id,
            WebhookSubscription.is_active.is_(True),
        )
    )
    subs = [s for s in result.scalars().all() if event in s.events]

    if not subs:
        return 0

    payload = json.dumps(
        {
            "event": event,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        },
        default=str,
    ).encode()

    delivered = 0
    async with httpx.AsyncClient(timeout=10) as client:
        for sub in subs:
            signature = _sign_payload(payload, sub.secret)
            try:
                resp = await client.post(
                    sub.url,
                    content=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-AIHM-Signature": signature,
                        "X-AIHM-Event": event,
                    },
                )
                if resp.status_code < 300:
                    delivered += 1
                else:
                    logger.warning(
                        "webhook_delivery_failed",
                        url=sub.url,
                        status=resp.status_code,
                        event=event,
                    )
            except Exception:
                logger.warning("webhook_delivery_error", url=sub.url, event=event)

    return delivered
