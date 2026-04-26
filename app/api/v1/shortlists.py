"""Endpoints shortlists candidats — Phase 1.2 V1_ROADMAP.

GET    /shortlists                              liste shortlists du tenant
POST   /shortlists                              cree une shortlist
GET    /shortlists/{id}                         detail + items
PATCH  /shortlists/{id}                         modifie meta (name/description/position_id)
DELETE /shortlists/{id}                         delete (cascade items)
POST   /shortlists/{id}/candidates              ajoute UN candidat
POST   /shortlists/{id}/candidates/bulk         ajoute PLUSIEURS candidats (depuis CandidatesPage)
DELETE /shortlists/{id}/candidates/{cand_id}    retire un candidat
"""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import asc, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.candidate import Candidate
from app.models.position import Position
from app.models.shortlist import Shortlist, ShortlistCandidate
from app.models.user import User
from app.schemas.shortlist import (
    AddCandidateToShortlist,
    BulkAddCandidates,
    ShortlistCreate,
    ShortlistDetailResponse,
    ShortlistItemResponse,
    ShortlistOwner,
    ShortlistResponse,
    ShortlistUpdate,
)

router = APIRouter(prefix="/shortlists", tags=["shortlists"])


def _build_response(s: Shortlist, owner: User, position_title: str | None, count: int) -> ShortlistResponse:
    return ShortlistResponse(
        id=s.id,
        tenant_id=s.tenant_id,
        owner=ShortlistOwner(
            id=owner.id,
            full_name=getattr(owner, "full_name", None),
            email=owner.email,
        ),
        position_id=s.position_id,
        position_title=position_title,
        name=s.name,
        description=s.description,
        candidates_count=count,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


async def _get_shortlist_or_404(
    shortlist_id: UUID, current_user: User, db: AsyncSession
) -> Shortlist:
    result = await db.execute(
        select(Shortlist).where(
            Shortlist.id == shortlist_id,
            Shortlist.tenant_id == current_user.tenant_id,
        )
    )
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Shortlist introuvable")
    return s


@router.get("", response_model=list[ShortlistResponse])
async def list_shortlists(
    position_id: UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Liste toutes les shortlists du tenant. Filtre optionnel par position."""
    query = (
        select(
            Shortlist,
            User,
            Position.title.label("position_title"),
            func.count(ShortlistCandidate.id).label("count"),
        )
        .join(User, User.id == Shortlist.owner_id)
        .outerjoin(Position, Position.id == Shortlist.position_id)
        .outerjoin(ShortlistCandidate, ShortlistCandidate.shortlist_id == Shortlist.id)
        .where(Shortlist.tenant_id == current_user.tenant_id)
        .group_by(Shortlist.id, User.id, Position.title)
        .order_by(desc(Shortlist.created_at))
    )
    if position_id:
        query = query.where(Shortlist.position_id == position_id)

    result = await db.execute(query)
    rows = result.all()
    return [_build_response(s, u, pt, c) for s, u, pt, c in rows]


@router.post("", response_model=ShortlistResponse, status_code=status.HTTP_201_CREATED)
async def create_shortlist(
    payload: ShortlistCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cree une shortlist (vide). Ajout des candidats via /shortlists/{id}/candidates."""
    if payload.position_id:
        # Verifie que la position appartient au tenant
        pos_res = await db.execute(
            select(Position).where(
                Position.id == payload.position_id,
                Position.tenant_id == current_user.tenant_id,
            )
        )
        if not pos_res.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Position invalide")

    sl = Shortlist(
        tenant_id=current_user.tenant_id,
        owner_id=current_user.id,
        position_id=payload.position_id,
        name=payload.name,
        description=payload.description,
    )
    db.add(sl)
    await db.commit()
    await db.refresh(sl)

    pos_title = None
    if sl.position_id:
        r = await db.execute(select(Position.title).where(Position.id == sl.position_id))
        pos_title = r.scalar_one_or_none()

    return _build_response(sl, current_user, pos_title, 0)


@router.get("/{shortlist_id}", response_model=ShortlistDetailResponse)
async def get_shortlist(
    shortlist_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Detail d'une shortlist : meta + items (candidats avec score + status)."""
    s = await _get_shortlist_or_404(shortlist_id, current_user, db)

    owner_res = await db.execute(select(User).where(User.id == s.owner_id))
    owner = owner_res.scalar_one()

    pos_title = None
    if s.position_id:
        r = await db.execute(select(Position.title).where(Position.id == s.position_id))
        pos_title = r.scalar_one_or_none()

    # Items avec join sur Candidate pour score + nom + status
    items_res = await db.execute(
        select(ShortlistCandidate, Candidate)
        .join(Candidate, Candidate.id == ShortlistCandidate.candidate_id)
        .where(ShortlistCandidate.shortlist_id == s.id)
        .order_by(asc(ShortlistCandidate.position), asc(ShortlistCandidate.added_at))
    )
    items = []
    for sc, cand in items_res.all():
        items.append(
            ShortlistItemResponse(
                id=sc.id,
                candidate_id=cand.id,
                candidate_name=cand.name,
                candidate_email=cand.email,
                cv_score=getattr(cand, "cv_score", None),
                pipeline_status=getattr(cand, "pipeline_status", None),
                note=sc.note,
                position=sc.position,
                added_at=sc.added_at,
                added_by=sc.added_by,
            )
        )

    base = _build_response(s, owner, pos_title, len(items))
    return ShortlistDetailResponse(**base.model_dump(), items=items)


@router.patch("/{shortlist_id}", response_model=ShortlistResponse)
async def update_shortlist(
    shortlist_id: UUID,
    payload: ShortlistUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Modifie meta d'une shortlist. Owner uniquement."""
    s = await _get_shortlist_or_404(shortlist_id, current_user, db)
    if s.owner_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Modification reservee au proprietaire")

    if payload.name is not None:
        s.name = payload.name
    if payload.description is not None:
        s.description = payload.description
    if payload.position_id is not None:
        # Verif tenant si non-null
        if payload.position_id:
            pos_res = await db.execute(
                select(Position).where(
                    Position.id == payload.position_id,
                    Position.tenant_id == current_user.tenant_id,
                )
            )
            if not pos_res.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="Position invalide")
        s.position_id = payload.position_id

    s.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(s)

    owner_res = await db.execute(select(User).where(User.id == s.owner_id))
    owner = owner_res.scalar_one()
    pos_title = None
    if s.position_id:
        r = await db.execute(select(Position.title).where(Position.id == s.position_id))
        pos_title = r.scalar_one_or_none()

    count_res = await db.execute(
        select(func.count(ShortlistCandidate.id)).where(ShortlistCandidate.shortlist_id == s.id)
    )
    count = count_res.scalar_one()
    return _build_response(s, owner, pos_title, count)


@router.delete("/{shortlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shortlist(
    shortlist_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Supprime une shortlist (owner ou admin). Cascade sur items."""
    s = await _get_shortlist_or_404(shortlist_id, current_user, db)
    if s.owner_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Suppression reservee au proprietaire")

    await db.delete(s)
    await db.commit()


# -- Items management ---------------------------------------------------------

async def _add_candidate(
    shortlist: Shortlist,
    candidate_id: UUID,
    note: str | None,
    current_user: User,
    db: AsyncSession,
) -> ShortlistCandidate | None:
    """Helper interne — return None si deja present (idempotent)."""
    # Verif candidat dans le tenant
    cand_res = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    if not cand_res.scalar_one_or_none():
        raise HTTPException(status_code=404, detail=f"Candidat {candidate_id} introuvable")

    # Idempotent : skip si deja dans la shortlist
    existing = await db.execute(
        select(ShortlistCandidate).where(
            ShortlistCandidate.shortlist_id == shortlist.id,
            ShortlistCandidate.candidate_id == candidate_id,
        )
    )
    if existing.scalar_one_or_none():
        return None

    # Position auto = max + 1 pour ranger en queue
    pos_res = await db.execute(
        select(func.coalesce(func.max(ShortlistCandidate.position), 0))
        .where(ShortlistCandidate.shortlist_id == shortlist.id)
    )
    next_pos = (pos_res.scalar_one() or 0) + 1

    sc = ShortlistCandidate(
        shortlist_id=shortlist.id,
        candidate_id=candidate_id,
        added_by=current_user.id,
        position=next_pos,
        note=note,
    )
    db.add(sc)
    return sc


@router.post(
    "/{shortlist_id}/candidates",
    response_model=ShortlistItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_candidate(
    shortlist_id: UUID,
    payload: AddCandidateToShortlist,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ajoute un candidat. Idempotent (409 si deja present)."""
    s = await _get_shortlist_or_404(shortlist_id, current_user, db)
    sc = await _add_candidate(s, payload.candidate_id, payload.note, current_user, db)
    if sc is None:
        raise HTTPException(status_code=409, detail="Candidat deja dans la shortlist")
    s.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sc)

    cand_res = await db.execute(select(Candidate).where(Candidate.id == sc.candidate_id))
    cand = cand_res.scalar_one()
    return ShortlistItemResponse(
        id=sc.id,
        candidate_id=cand.id,
        candidate_name=cand.name,
        candidate_email=cand.email,
        cv_score=getattr(cand, "cv_score", None),
        pipeline_status=getattr(cand, "pipeline_status", None),
        note=sc.note,
        position=sc.position,
        added_at=sc.added_at,
        added_by=sc.added_by,
    )


@router.post("/{shortlist_id}/candidates/bulk", response_model=ShortlistDetailResponse)
async def bulk_add_candidates(
    shortlist_id: UUID,
    payload: BulkAddCandidates,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ajoute plusieurs candidats d'un coup (selection multiple côté UI).

    Idempotent : les déjà-présents sont silencieusement ignorés.
    Renvoie le détail mis à jour pour eviter un round-trip côté client.
    """
    s = await _get_shortlist_or_404(shortlist_id, current_user, db)

    added = 0
    for cand_id in payload.candidate_ids:
        sc = await _add_candidate(s, cand_id, None, current_user, db)
        if sc is not None:
            added += 1

    if added > 0:
        s.updated_at = datetime.now(timezone.utc)

    await db.commit()
    # Reload via get_shortlist logic
    return await get_shortlist(shortlist_id, current_user, db)


@router.delete(
    "/{shortlist_id}/candidates/{candidate_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_candidate(
    shortlist_id: UUID,
    candidate_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retire un candidat de la shortlist."""
    s = await _get_shortlist_or_404(shortlist_id, current_user, db)
    res = await db.execute(
        select(ShortlistCandidate).where(
            ShortlistCandidate.shortlist_id == s.id,
            ShortlistCandidate.candidate_id == candidate_id,
        )
    )
    sc = res.scalar_one_or_none()
    if not sc:
        raise HTTPException(status_code=404, detail="Candidat absent de la shortlist")
    await db.delete(sc)
    s.updated_at = datetime.now(timezone.utc)
    await db.commit()
