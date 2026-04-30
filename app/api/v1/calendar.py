"""Calendar OAuth integration endpoints (Google, Outlook).

Real OAuth2 flow backed by app.services.calendar_oauth:
- POST /calendar/oauth/{provider}/authorize → returns authorize URL
  (frontend opens it in a popup or redirects user)
- POST /calendar/oauth/{provider}/callback  → exchanges code for tokens
  (verifies CSRF state, encrypts and stores in user_integrations)
- GET  /calendar/status                     → which providers the user has connected
- DELETE /calendar/integrations/{provider}  → disconnect (sets status=revoked)

Provider keys in URLs: google | outlook  (mapped internally to UserIntegration
provider strings: google_calendar | microsoft_calendar).
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models import User
from app.models.user_integration import UserIntegration
from app.services.calendar_oauth import (
    PROVIDER_GOOGLE,
    PROVIDER_MICROSOFT,
    build_google_authorize_url,
    build_microsoft_authorize_url,
    encrypt_token,
    exchange_google_code,
    exchange_microsoft_code,
    verify_state,
)

router = APIRouter(prefix="/calendar", tags=["calendar"])


_PROVIDER_MAP = {
    "google": PROVIDER_GOOGLE,
    "outlook": PROVIDER_MICROSOFT,
}


class AuthorizeResponse(BaseModel):
    auth_url: str
    provider: str


class CallbackRequest(BaseModel):
    code: str
    state: str


class IntegrationStatus(BaseModel):
    provider: str
    connected: bool
    account_email: str | None = None
    expires_at: datetime | None = None


# ─── Authorize ────────────────────────────────────────────────────────────────


@router.post("/oauth/google/authorize", response_model=AuthorizeResponse)
async def authorize_google_calendar(current_user: User = Depends(get_current_user)):
    try:
        auth_url = build_google_authorize_url(str(current_user.id))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return AuthorizeResponse(auth_url=auth_url, provider="google")


@router.post("/oauth/outlook/authorize", response_model=AuthorizeResponse)
async def authorize_outlook_calendar(current_user: User = Depends(get_current_user)):
    try:
        auth_url = build_microsoft_authorize_url(str(current_user.id))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return AuthorizeResponse(auth_url=auth_url, provider="outlook")


# ─── Callback ─────────────────────────────────────────────────────────────────


async def _store_integration(
    db: AsyncSession,
    user: User,
    provider: str,
    token_response: dict,
) -> UserIntegration:
    """Upsert UserIntegration row with encrypted tokens."""
    access_token = token_response.get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="provider returned no access_token")

    refresh_token = token_response.get("refresh_token")
    expires_in = token_response.get("expires_in")
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        if isinstance(expires_in, int)
        else None
    )

    res = await db.execute(
        select(UserIntegration).where(
            UserIntegration.user_id == user.id,
            UserIntegration.provider == provider,
        )
    )
    integration = res.scalar_one_or_none()
    if integration is None:
        integration = UserIntegration(
            tenant_id=user.tenant_id,
            user_id=user.id,
            provider=provider,
            scopes=token_response.get("scope", "").split(" ") if token_response.get("scope") else None,
        )
        db.add(integration)

    integration.access_token_encrypted = encrypt_token(access_token)
    if refresh_token:
        # Microsoft re-issues; Google only issues on first consent (prompt=consent helps).
        integration.refresh_token_encrypted = encrypt_token(refresh_token)
    integration.expires_at = expires_at
    integration.status = "active"
    integration.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(integration)
    return integration


@router.post("/oauth/google/callback")
async def handle_google_callback(
    payload: CallbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_state(payload.state, str(current_user.id), PROVIDER_GOOGLE):
        raise HTTPException(status_code=400, detail="invalid or expired state")

    try:
        token_response = await exchange_google_code(payload.code)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"google token exchange failed: {e}")

    await _store_integration(db, current_user, PROVIDER_GOOGLE, token_response)

    return {
        "status": "connected",
        "provider": "google",
        "message": "Google Calendar connected successfully",
    }


@router.post("/oauth/outlook/callback")
async def handle_outlook_callback(
    payload: CallbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_state(payload.state, str(current_user.id), PROVIDER_MICROSOFT):
        raise HTTPException(status_code=400, detail="invalid or expired state")

    try:
        token_response = await exchange_microsoft_code(payload.code)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"microsoft token exchange failed: {e}")

    await _store_integration(db, current_user, PROVIDER_MICROSOFT, token_response)

    return {
        "status": "connected",
        "provider": "outlook",
        "message": "Outlook Calendar connected successfully",
    }


# ─── Status / Disconnect ──────────────────────────────────────────────────────


@router.get("/status", response_model=list[IntegrationStatus])
async def list_integrations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(UserIntegration).where(UserIntegration.user_id == current_user.id)
    )
    rows = res.scalars().all()
    by_provider = {r.provider: r for r in rows}

    out = []
    for label, internal in (("google", PROVIDER_GOOGLE), ("outlook", PROVIDER_MICROSOFT)):
        row = by_provider.get(internal)
        out.append(IntegrationStatus(
            provider=label,
            connected=bool(row and row.status == "active"),
            account_email=row.account_email if row else None,
            expires_at=row.expires_at if row else None,
        ))
    return out


@router.delete("/integrations/{provider}")
async def disconnect_integration(
    provider: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    internal = _PROVIDER_MAP.get(provider)
    if internal is None:
        raise HTTPException(status_code=400, detail="unknown provider")

    res = await db.execute(
        select(UserIntegration).where(
            UserIntegration.user_id == current_user.id,
            UserIntegration.provider == internal,
        )
    )
    integration = res.scalar_one_or_none()
    if integration is None:
        raise HTTPException(status_code=404, detail="integration not found")

    integration.status = "revoked"
    integration.access_token_encrypted = None
    integration.refresh_token_encrypted = None
    integration.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return {"status": "disconnected", "provider": provider}


# ─── Stub endpoints (UI-facing, real impl pending Calendar API integration) ────
# These are kept so the existing frontend keeps working. They will be wired up
# to actual Calendar API calls (events.list, events.insert, freeBusy.query)
# once the OAuth round-trip is exercised end-to-end against real provider apps.


@router.get("/sync")
async def sync_calendar(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return {"status": "syncing", "interviews_synced": 0}


@router.get("/events")
async def get_calendar_events(
    days_ahead: int = 30,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return {"provider": "google", "events": [], "next_sync": None}


@router.post("/reschedule/{interview_id}")
async def reschedule_with_calendar(
    interview_id: UUID,
    new_time: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return {
        "status": "rescheduled",
        "interview_id": str(interview_id),
        "new_time": new_time,
        "calendar_updated": False,
    }


@router.post("/availability")
async def get_recruiter_availability(
    start_date: str,
    end_date: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return {
        "recruiter_id": str(current_user.id),
        "available_slots": [],
    }
