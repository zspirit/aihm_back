"""Referral endpoints — Phase 4.3 V1_ROADMAP.

GET  /me/referral-link    : recupere/genere le lien personnel du user courant
POST /public/refer/{token}/apply : form public referral pre-rempli (depuis l'employe qui partage)

Le source='referral' + referrer_user_id sont stamps sur application.
"""
import secrets
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.position import Position
from app.models.user import User

router = APIRouter(tags=["referrals"])


class ReferralLink(BaseModel):
    token: str
    url_template: str  # frontend rendra ?ref={token}


@router.get("/me/referral-link", response_model=ReferralLink)
async def my_referral_link(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Recupere ou genere le token referral personnel."""
    if not getattr(current_user, "referral_token", None):
        token = secrets.token_urlsafe(24)
        current_user.referral_token = token
        await db.commit()
    else:
        token = current_user.referral_token
    return ReferralLink(
        token=token,
        url_template=f"/refer/{token}",  # le front concatenera FRONTEND_URL
    )


public_router = APIRouter(prefix="/public/refer", tags=["public-referrals"])


@public_router.get("/{token}/info")
async def referral_info(
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Info publique : nom du recommandeur (pour pre-remplir le form public)."""
    res = await db.execute(select(User).where(User.referral_token == token))
    user = res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Lien introuvable")
    return {
        "referrer_name": getattr(user, "full_name", None) or user.email.split("@")[0],
        "tenant_id": str(user.tenant_id),
    }


@public_router.post("/{token}/apply")
async def referral_apply(
    token: str,
    name: str = Form(...),
    email: EmailStr = Form(...),
    phone: Optional[str] = Form(None),
    position_id: Optional[UUID] = Form(None),
    cover_letter: Optional[str] = Form(None),
    cv: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
):
    """Form public de referral : applique le candidat avec source=referral."""
    res = await db.execute(select(User).where(User.referral_token == token))
    referrer = res.scalar_one_or_none()
    if not referrer:
        raise HTTPException(status_code=404, detail="Lien introuvable")

    cand = Candidate(
        id=uuid4(),
        tenant_id=referrer.tenant_id,
        position_id=position_id,
        name=name,
        email=email,
        phone=phone,
        pipeline_status="new",
        cv_parsed_data={"cover_letter": cover_letter} if cover_letter else None,
    )
    db.add(cand)
    await db.flush()

    if position_id:
        # Verifie position du tenant + active
        pos_res = await db.execute(
            select(Position).where(
                Position.id == position_id,
                Position.tenant_id == referrer.tenant_id,
            )
        )
        if pos_res.scalar_one_or_none():
            app = Application(
                candidate_id=cand.id,
                position_id=position_id,
                tenant_id=referrer.tenant_id,
                source="referral",
                referrer_user_id=referrer.id,
            )
            db.add(app)

    await db.commit()
    return {
        "status": "received",
        "message": f"Merci ! Votre candidature a ete envoyee via la recommandation de {getattr(referrer, 'full_name', None) or referrer.email}.",
        "candidate_id": str(cand.id),
    }
