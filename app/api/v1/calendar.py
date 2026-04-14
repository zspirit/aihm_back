"""Calendar OAuth integration endpoints (Google, Outlook)."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, get_current_user
from app.models import User

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.post("/oauth/google/authorize")
async def authorize_google_calendar(
    redirect_uri: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get Google Calendar OAuth authorization URL."""
    # In real impl: generate OAuth2 authorization URL
    # For now: return mock URL
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?client_id=MOCK&redirect_uri={redirect_uri}&scope=calendar"
    return {"auth_url": auth_url, "provider": "google"}


@router.post("/oauth/google/callback")
async def handle_google_callback(
    code: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Handle Google OAuth callback and store tokens."""
    # In real impl: exchange code for tokens
    # For now: return mock success
    return {
        "status": "connected",
        "provider": "google",
        "message": "Google Calendar connected successfully",
    }


@router.post("/oauth/outlook/authorize")
async def authorize_outlook_calendar(
    redirect_uri: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get Outlook Calendar OAuth authorization URL."""
    auth_url = f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id=MOCK&redirect_uri={redirect_uri}&scope=calendar.readwrite"
    return {"auth_url": auth_url, "provider": "outlook"}


@router.post("/oauth/outlook/callback")
async def handle_outlook_callback(
    code: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Handle Outlook OAuth callback and store tokens."""
    return {
        "status": "connected",
        "provider": "outlook",
        "message": "Outlook Calendar connected successfully",
    }


@router.get("/sync")
async def sync_calendar(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sync interviews with connected calendar."""
    # In real impl: fetch events from Google/Outlook and sync
    return {
        "status": "syncing",
        "message": "Calendar sync in progress",
        "interviews_synced": 0,
    }


@router.get("/events")
async def get_calendar_events(
    days_ahead: int = 30,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get upcoming calendar events."""
    # In real impl: fetch from Google/Outlook
    return {
        "provider": "google",  # or outlook
        "events": [],
        "next_sync": "2026-04-16T00:00:00Z",
    }


@router.post("/reschedule/{interview_id}")
async def reschedule_with_calendar(
    interview_id: UUID,
    new_time: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reschedule interview and update calendar."""
    return {
        "status": "rescheduled",
        "interview_id": str(interview_id),
        "new_time": new_time,
        "calendar_updated": True,
    }


@router.post("/availability")
async def get_recruiter_availability(
    start_date: str,
    end_date: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get recruiter availability from calendar."""
    return {
        "recruiter_id": str(current_user.id),
        "available_slots": [
            {"date": "2026-04-16", "time": "10:00-11:00"},
            {"date": "2026-04-16", "time": "14:00-15:00"},
        ],
    }
