from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.candidate import Candidate
from app.models.consent import Consent
from app.models.position import Position
from app.models.tenant import Tenant
from app.schemas.consent import ConsentGrantRequest, ConsentPageResponse, ConsentResponse

router = APIRouter(prefix="/consent", tags=["consent"])


@router.get("/{token}", response_model=ConsentPageResponse)
async def get_consent_page(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Consent).where(Consent.token == token))
    consent = result.scalar_one_or_none()
    if not consent:
        raise HTTPException(status_code=404, detail="Lien de consentement invalide")

    candidate_result = await db.execute(
        select(Candidate).where(Candidate.id == consent.candidate_id)
    )
    candidate = candidate_result.scalar_one_or_none()

    position_result = await db.execute(
        select(Position).where(Position.id == candidate.position_id)
    )
    position = position_result.scalar_one_or_none()

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == candidate.tenant_id))
    tenant = tenant_result.scalar_one_or_none()

    all_consents = await db.execute(
        select(Consent).where(Consent.candidate_id == candidate.id)
    )
    consent_types = [c.type for c in all_consents.scalars().all()]

    return ConsentPageResponse(
        candidate_name=candidate.name,
        company_name=tenant.name,
        position_title=position.title,
        consent_types=consent_types,
        already_granted=consent.granted,
    )


@router.post("/{token}", response_model=ConsentResponse)
@limiter.limit("10/minute")
async def grant_consent(
    token: str,
    data: ConsentGrantRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Consent).where(Consent.token == token))
    consent = result.scalar_one_or_none()
    if not consent:
        raise HTTPException(status_code=404, detail="Lien de consentement invalide")

    if consent.granted:
        raise HTTPException(status_code=400, detail="Consentement deja accorde")

    consent.granted = data.granted
    consent.granted_at = datetime.now(timezone.utc)
    consent.channel = "web"
    consent.ip_address = request.client.host if request.client else None

    all_consents = await db.execute(
        select(Consent).where(
            Consent.candidate_id == consent.candidate_id,
            Consent.granted.is_(False),
        )
    )
    for c in all_consents.scalars().all():
        c.granted = data.granted
        c.granted_at = datetime.now(timezone.utc)
        c.channel = "web"
        c.ip_address = request.client.host if request.client else None

    candidate_result = await db.execute(
        select(Candidate).where(Candidate.id == consent.candidate_id)
    )
    candidate = candidate_result.scalar_one_or_none()
    if candidate and data.granted:
        candidate.pipeline_status = "consent_given"

    return ConsentResponse(
        id=str(consent.id),
        candidate_id=str(consent.candidate_id),
        type=consent.type,
        granted=consent.granted,
        granted_at=consent.granted_at,
        channel=consent.channel,
    )
