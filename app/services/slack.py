"""Slack outbound notifications via Incoming Webhooks.

Each tenant configures its own Slack webhook URL (stored on the tenant).
Slack URLs look like:
  https://hooks.slack.com/services/T.../B.../...

Events we push:
- candidate.new            → "New candidate {name} applied to {position}"
- interview.scheduled      → "Interview scheduled with {name} at {time}"
- offer.signed             → "Offer accepted by {name} for {position}"
- candidate.cv_analyzed    → "{name}: CV scored {score}/100"

Fire-and-forget: a Slack outage must never break a Celery task. All
publish helpers swallow exceptions and log instead.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class SlackError(Exception):
    """Internal — only raised by send_message_strict for tests/admin endpoints."""


def _format_block(text: str, fields: dict[str, Any] | None = None) -> dict[str, Any]:
    blocks: list[dict] = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    if fields:
        blocks.append({
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*{k}*\n{v}"} for k, v in fields.items()
            ],
        })
    return {"blocks": blocks, "text": text}  # text = fallback for old clients


def send_message_sync(webhook_url: str, text: str, fields: dict[str, Any] | None = None) -> bool:
    """Sync version (Celery worker context). Returns True on 2xx, False otherwise."""
    if not webhook_url:
        return False
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.post(webhook_url, json=_format_block(text, fields))
        return 200 <= r.status_code < 300
    except Exception:
        logger.warning("slack_send_failed", exc_info=True)
        return False


async def send_message_async(
    webhook_url: str, text: str, fields: dict[str, Any] | None = None
) -> bool:
    """Async version (FastAPI context)."""
    if not webhook_url:
        return False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(webhook_url, json=_format_block(text, fields))
        return 200 <= r.status_code < 300
    except Exception:
        logger.warning("slack_send_async_failed", exc_info=True)
        return False


async def send_message_strict(
    webhook_url: str, text: str, fields: dict[str, Any] | None = None
) -> None:
    """Strict version — raises SlackError on failure. Used by /test endpoint
    so the admin sees what went wrong. Do NOT use from workers/triggers."""
    if not webhook_url:
        raise SlackError("no webhook URL configured")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(webhook_url, json=_format_block(text, fields))
    except httpx.RequestError as e:
        raise SlackError(f"network error: {e}") from e
    if not (200 <= r.status_code < 300):
        raise SlackError(f"slack returned {r.status_code}: {r.text[:200]}")


# ─── Event-specific helpers ───────────────────────────────────────────────────


def notify_new_candidate(webhook_url: str, candidate_name: str, position_title: str) -> bool:
    return send_message_sync(
        webhook_url,
        f":bust_in_silhouette: *New candidate*: {candidate_name}",
        {"Position": position_title},
    )


def notify_interview_scheduled(
    webhook_url: str, candidate_name: str, scheduled_at_iso: str
) -> bool:
    return send_message_sync(
        webhook_url,
        f":calendar: *Interview scheduled* with {candidate_name}",
        {"When": scheduled_at_iso},
    )


def notify_offer_signed(
    webhook_url: str, candidate_name: str, position_title: str
) -> bool:
    return send_message_sync(
        webhook_url,
        f":white_check_mark: *Offer signed* by {candidate_name}",
        {"Position": position_title},
    )


def notify_cv_analyzed(webhook_url: str, candidate_name: str, score: float) -> bool:
    return send_message_sync(
        webhook_url,
        f":bar_chart: *CV analyzed*: {candidate_name} — score {round(score)}/100",
    )
