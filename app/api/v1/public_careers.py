"""Career page publique — Phase 3.1 V1_ROADMAP.

Endpoints SANS auth (rate-limited via slowapi sur l'app).

GET  /public/careers/{tenant_slug}              liste positions actives
GET  /public/careers/{tenant_slug}/{pos_slug}   detail position
POST /public/careers/{tenant_slug}/{pos_slug}/apply   form public d'application

Le tenant doit avoir public_career_page=true et public_slug defini.
"""
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.position import Position
from app.models.tenant import Tenant

router = APIRouter(prefix="/public/careers", tags=["public-careers"])


class PublicPositionSummary(BaseModel):
    id: UUID
    title: str
    slug: Optional[str] = None
    seniority_level: str
    description_preview: Optional[str] = None


class PublicTenantInfo(BaseModel):
    name: str
    slug: str
    branding: dict = Field(default_factory=dict)


class PublicCareersResponse(BaseModel):
    tenant: PublicTenantInfo
    positions: list[PublicPositionSummary]


class PublicPositionDetail(BaseModel):
    id: UUID
    title: str
    slug: Optional[str] = None
    seniority_level: str
    description: Optional[str] = None
    required_skills: list = Field(default_factory=list)


@router.get("/{tenant_slug}", response_model=PublicCareersResponse)
async def list_public_positions(
    tenant_slug: str,
    db: AsyncSession = Depends(get_db),
):
    """Liste les positions actives d'un tenant a career page publique."""
    res = await db.execute(
        select(Tenant).where(
            Tenant.public_slug == tenant_slug,
            Tenant.public_career_page == True,  # noqa: E712
        )
    )
    tenant = res.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Career page introuvable")

    pos_res = await db.execute(
        select(Position).where(
            Position.tenant_id == tenant.id,
            Position.status == "active",
        )
    )
    positions = pos_res.scalars().all()
    return PublicCareersResponse(
        tenant=PublicTenantInfo(
            name=tenant.name,
            slug=tenant.public_slug,
            branding=getattr(tenant, "public_branding", {}) or {},
        ),
        positions=[
            PublicPositionSummary(
                id=p.id,
                title=p.title,
                slug=getattr(p, "public_slug", None),
                seniority_level=p.seniority_level,
                description_preview=(p.description[:200] + "...") if p.description and len(p.description) > 200 else p.description,
            )
            for p in positions
        ],
    )


@router.get("/{tenant_slug}/{position_id_or_slug}", response_model=PublicPositionDetail)
async def get_public_position(
    tenant_slug: str,
    position_id_or_slug: str,
    db: AsyncSession = Depends(get_db),
):
    """Detail d'une position publique — par UUID ou slug."""
    tenant_res = await db.execute(
        select(Tenant).where(
            Tenant.public_slug == tenant_slug,
            Tenant.public_career_page == True,  # noqa: E712
        )
    )
    tenant = tenant_res.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Career page introuvable")

    # Try UUID, fallback slug
    pos = None
    try:
        pos_id = UUID(position_id_or_slug)
        res = await db.execute(
            select(Position).where(
                Position.id == pos_id,
                Position.tenant_id == tenant.id,
                Position.status == "active",
            )
        )
        pos = res.scalar_one_or_none()
    except ValueError:
        pass
    if not pos:
        res = await db.execute(
            select(Position).where(
                Position.public_slug == position_id_or_slug,
                Position.tenant_id == tenant.id,
                Position.status == "active",
            )
        )
        pos = res.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Poste introuvable")

    return PublicPositionDetail(
        id=pos.id,
        title=pos.title,
        slug=getattr(pos, "public_slug", None),
        seniority_level=pos.seniority_level,
        description=pos.description,
        required_skills=pos.required_skills or [],
    )


@router.post("/{tenant_slug}/{position_id}/apply")
async def public_apply(
    tenant_slug: str,
    position_id: UUID,
    name: str = Form(...),
    email: EmailStr = Form(...),
    phone: Optional[str] = Form(None),
    cover_letter: Optional[str] = Form(None),
    cv: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
):
    """Form public : cree candidate + application avec source='direct_apply'.

    Pas de stockage S3 du CV ici (extension future). On enregistre les meta.
    """
    tenant_res = await db.execute(
        select(Tenant).where(
            Tenant.public_slug == tenant_slug,
            Tenant.public_career_page == True,  # noqa: E712
        )
    )
    tenant = tenant_res.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Career page introuvable")

    pos_res = await db.execute(
        select(Position).where(
            Position.id == position_id,
            Position.tenant_id == tenant.id,
            Position.status == "active",
        )
    )
    pos = pos_res.scalar_one_or_none()
    if not pos:
        raise HTTPException(status_code=404, detail="Poste introuvable")

    cand = Candidate(
        id=uuid4(),
        tenant_id=tenant.id,
        position_id=pos.id,
        name=name,
        email=email,
        phone=phone,
        pipeline_status="new",
        cv_parsed_data={"cover_letter": cover_letter} if cover_letter else None,
    )
    db.add(cand)
    await db.flush()

    app = Application(
        candidate_id=cand.id,
        position_id=pos.id,
        tenant_id=tenant.id,
        source="direct_apply",
    )
    db.add(app)
    await db.commit()

    # TODO Phase 2.1 : envoyer email confirmation au candidat (template invitation)

    return {
        "status": "received",
        "message": "Votre candidature a bien ete envoyee. Nous vous contacterons sous peu.",
        "candidate_id": str(cand.id),
    }
