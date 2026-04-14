"""Offer Management endpoints (Phase 3)."""
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import APIRouter, Depends, HTTPException
import secrets

from app.core.dependencies import get_db, get_current_user
from app.models import Offer, Application, Enterprise, User
from app.schemas.offer import (
    OfferCreate,
    OfferUpdate,
    OfferResponse,
    OfferSend,
    OfferSign,
    OfferReject,
)

router = APIRouter(prefix="/offers", tags=["offers"])


@router.post("/applications/{app_id}/offers", response_model=OfferResponse, status_code=201)
async def create_offer_from_application(
    app_id: UUID,
    payload: OfferCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create an offer for an application."""
    # Fetch application
    application = await db.get(Application, app_id)
    if not application or application.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Application not found")

    # Fetch position to get enterprise_id
    position = application.position
    if not position.enterprise_id:
        raise HTTPException(status_code=400, detail="Position must be linked to an enterprise")

    # Check if offer already exists
    existing_offer = await db.execute(
        select(Offer).where(Offer.application_id == app_id)
    )
    if existing_offer.scalars().first():
        raise HTTPException(status_code=409, detail="Offer already exists for this application")

    # Create offer
    offer = Offer(
        tenant_id=current_user.tenant_id,
        enterprise_id=position.enterprise_id,
        application_id=app_id,
        **payload.model_dump(),
        created_by=current_user.id,
        status="draft",
    )
    db.add(offer)
    await db.commit()
    await db.refresh(offer)
    return offer


@router.get("", response_model=list[OfferResponse])
async def list_offers(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all offers for the tenant."""
    query = select(Offer).where(Offer.tenant_id == current_user.tenant_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{offer_id}", response_model=OfferResponse)
async def get_offer(
    offer_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific offer."""
    offer = await db.get(Offer, offer_id)
    if not offer or offer.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Offer not found")
    return offer


@router.put("/{offer_id}", response_model=OfferResponse)
async def update_offer(
    offer_id: UUID,
    payload: OfferUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an offer (only draft offers can be updated)."""
    offer = await db.get(Offer, offer_id)
    if not offer or offer.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Offer not found")

    if offer.status != "draft":
        raise HTTPException(status_code=400, detail="Only draft offers can be updated")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(offer, field, value)

    offer.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(offer)
    return offer


@router.post("/{offer_id}/send", response_model=OfferResponse)
async def send_offer(
    offer_id: UUID,
    payload: OfferSend,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send an offer to candidate (generates signature token)."""
    offer = await db.get(Offer, offer_id)
    if not offer or offer.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Offer not found")

    if offer.status != "draft":
        raise HTTPException(status_code=400, detail="Only draft offers can be sent")

    # Generate signature token
    offer.signature_token = secrets.token_urlsafe(32)
    offer.status = "sent"
    offer.sent_at = datetime.now(timezone.utc)
    offer.expires_at = payload.expires_at
    offer.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(offer)
    return offer


@router.post("/{offer_id}/sign", response_model=OfferResponse)
async def sign_offer(
    offer_id: UUID,
    payload: OfferSign,
    db: AsyncSession = Depends(get_db),
):
    """Sign an offer (callback from e-signature provider)."""
    offer = await db.get(Offer, offer_id)
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    if offer.signature_token != payload.signature_token:
        raise HTTPException(status_code=400, detail="Invalid signature token")

    if offer.status not in ["sent", "viewed"]:
        raise HTTPException(status_code=400, detail="Offer cannot be signed in current status")

    offer.status = "signed"
    offer.signed_at = datetime.now(timezone.utc)
    offer.signed_by = payload.signed_by
    offer.updated_at = datetime.now(timezone.utc)

    # Update application decision to "accepted"
    application = offer.application
    application.decision = "accepted"
    application.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(offer)
    return offer


@router.post("/{offer_id}/reject", response_model=OfferResponse)
async def reject_offer(
    offer_id: UUID,
    payload: OfferReject,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reject an offer."""
    offer = await db.get(Offer, offer_id)
    if not offer or offer.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Offer not found")

    if offer.status in ["signed", "rejected", "expired"]:
        raise HTTPException(status_code=400, detail="Offer cannot be rejected in current status")

    offer.status = "rejected"
    offer.rejected_at = datetime.now(timezone.utc)
    offer.rejection_reason = payload.rejection_reason
    offer.updated_at = datetime.now(timezone.utc)

    # Update application decision to "rejected"
    application = offer.application
    application.decision = "rejected"
    application.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(offer)
    return offer
