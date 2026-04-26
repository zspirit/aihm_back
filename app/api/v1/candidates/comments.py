"""Endpoints commentaires sur fiches candidats.

POST   /candidates/{id}/comments         créer (root ou réponse via parent_id)
GET    /candidates/{id}/comments         liste flat ordonnée chronologiquement
PATCH  /candidates/{id}/comments/{cid}   éditer (auteur uniquement)
DELETE /candidates/{id}/comments/{cid}   soft delete (auteur ou admin)

Mentions @username extraites au moment du write côté serveur (regex sur
l'email local part). Le champ mentioned_user_ids permet de notifier
ces utilisateurs dans une phase ultérieure (Phase 1.4 activity feed).
"""
import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import asc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.candidate import Candidate
from app.models.candidate_comment import CandidateComment
from app.models.user import User
from app.schemas.candidate_comment import (
    CandidateCommentCreate,
    CandidateCommentResponse,
    CandidateCommentUpdate,
    CommentAuthor,
)

router = APIRouter(tags=["candidates"])


# Regex @mention : capture l'email local part (avant @) ou un username compact.
# Ex: "@alice", "@john.doe" → matchent.
_MENTION_RE = re.compile(r"@([a-zA-Z0-9._-]+)")


async def _resolve_mentions(
    content: str, tenant_id: UUID, db: AsyncSession
) -> list[UUID]:
    """Extrait les @mentions du contenu et les résout en user_ids.

    Match prioritaire : email local part. Fallback : full_name compact.
    Retourne uniquement des users du même tenant.
    """
    handles = set(_MENTION_RE.findall(content))
    if not handles:
        return []

    # Cherche par préfixe email == handle (avant le @)
    # Ex: handle="alice" -> match user.email LIKE "alice@%"
    found: list[UUID] = []
    for handle in handles:
        result = await db.execute(
            select(User.id).where(
                User.tenant_id == tenant_id,
                User.email.ilike(f"{handle}@%"),
            )
        )
        uid = result.scalar_one_or_none()
        if uid:
            found.append(uid)
    return found


def _to_response(c: CandidateComment, author: User) -> CandidateCommentResponse:
    return CandidateCommentResponse(
        id=c.id,
        candidate_id=c.candidate_id,
        parent_id=c.parent_id,
        content=c.content if c.deleted_at is None else "[Commentaire supprime]",
        mentioned_user_ids=c.mentioned_user_ids or [],
        author=CommentAuthor(
            id=author.id,
            full_name=getattr(author, "full_name", None),
            email=author.email,
            role=author.role,
        ),
        created_at=c.created_at,
        edited_at=c.edited_at,
        is_deleted=c.deleted_at is not None,
    )


async def _check_candidate_access(
    candidate_id: UUID, current_user: User, db: AsyncSession
) -> Candidate:
    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")
    return candidate


@router.post(
    "/candidates/{candidate_id}/comments",
    response_model=CandidateCommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_comment(
    candidate_id: UUID,
    payload: CandidateCommentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Crée un commentaire (root ou réponse via parent_id)."""
    await _check_candidate_access(candidate_id, current_user, db)

    # Si parent_id, vérifier qu'il existe et qu'il est sur le même candidat
    if payload.parent_id:
        parent_res = await db.execute(
            select(CandidateComment).where(
                CandidateComment.id == payload.parent_id,
                CandidateComment.candidate_id == candidate_id,
                CandidateComment.tenant_id == current_user.tenant_id,
            )
        )
        if not parent_res.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Commentaire parent introuvable")

    mentioned = await _resolve_mentions(payload.content, current_user.tenant_id, db)

    comment = CandidateComment(
        tenant_id=current_user.tenant_id,
        candidate_id=candidate_id,
        author_id=current_user.id,
        parent_id=payload.parent_id,
        content=payload.content,
        mentioned_user_ids=[str(uid) for uid in mentioned] if mentioned else None,
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return _to_response(comment, current_user)


@router.get(
    "/candidates/{candidate_id}/comments",
    response_model=list[CandidateCommentResponse],
)
async def list_comments(
    candidate_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Liste tous les commentaires d'un candidat, ordre chronologique.

    Inclut les soft-deleted (avec content masqué) pour préserver le fil de
    discussion (un thread orphelin serait illisible).
    """
    await _check_candidate_access(candidate_id, current_user, db)

    result = await db.execute(
        select(CandidateComment, User)
        .join(User, User.id == CandidateComment.author_id)
        .where(
            CandidateComment.candidate_id == candidate_id,
            CandidateComment.tenant_id == current_user.tenant_id,
        )
        .order_by(asc(CandidateComment.created_at))
    )
    rows = result.all()
    return [_to_response(c, u) for c, u in rows]


@router.patch(
    "/candidates/{candidate_id}/comments/{comment_id}",
    response_model=CandidateCommentResponse,
)
async def update_comment(
    candidate_id: UUID,
    comment_id: UUID,
    payload: CandidateCommentUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Édite un commentaire — auteur uniquement, et pas si soft-deleted."""
    await _check_candidate_access(candidate_id, current_user, db)

    result = await db.execute(
        select(CandidateComment).where(
            CandidateComment.id == comment_id,
            CandidateComment.candidate_id == candidate_id,
            CandidateComment.tenant_id == current_user.tenant_id,
        )
    )
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Commentaire introuvable")
    if comment.deleted_at is not None:
        raise HTTPException(status_code=400, detail="Commentaire supprime")
    if comment.author_id != current_user.id:
        raise HTTPException(status_code=403, detail="Vous n'etes pas l'auteur")

    mentioned = await _resolve_mentions(payload.content, current_user.tenant_id, db)
    comment.content = payload.content
    comment.mentioned_user_ids = [str(uid) for uid in mentioned] if mentioned else None
    comment.edited_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(comment)
    return _to_response(comment, current_user)


@router.delete(
    "/candidates/{candidate_id}/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_comment(
    candidate_id: UUID,
    comment_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete d'un commentaire (auteur ou admin)."""
    await _check_candidate_access(candidate_id, current_user, db)

    result = await db.execute(
        select(CandidateComment).where(
            CandidateComment.id == comment_id,
            CandidateComment.candidate_id == candidate_id,
            CandidateComment.tenant_id == current_user.tenant_id,
        )
    )
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Commentaire introuvable")
    if comment.deleted_at is not None:
        return  # idempotent

    is_author = comment.author_id == current_user.id
    is_admin = current_user.role == "admin"
    if not (is_author or is_admin):
        raise HTTPException(status_code=403, detail="Suppression non autorisee")

    comment.deleted_at = datetime.now(timezone.utc)
    await db.commit()
