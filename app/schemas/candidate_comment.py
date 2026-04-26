"""Schemas pour les commentaires sur fiches candidats."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CandidateCommentCreate(BaseModel):
    """Crée un nouveau commentaire (root ou réponse via parent_id)."""

    content: str = Field(..., min_length=1, max_length=10000, description="Contenu markdown")
    parent_id: Optional[UUID] = Field(
        None, description="ID du commentaire parent pour les threads"
    )


class CandidateCommentUpdate(BaseModel):
    """Édite un commentaire (auteur uniquement)."""

    content: str = Field(..., min_length=1, max_length=10000)


class CommentAuthor(BaseModel):
    """Info auteur synthétique injectée dans la réponse."""

    id: UUID
    full_name: Optional[str] = None
    email: str
    role: str


class CandidateCommentResponse(BaseModel):
    """Réponse standard pour un commentaire."""

    id: UUID
    candidate_id: UUID
    parent_id: Optional[UUID] = None
    content: str
    mentioned_user_ids: list[UUID] = Field(default_factory=list)
    author: CommentAuthor
    created_at: datetime
    edited_at: Optional[datetime] = None
    is_deleted: bool = False

    class Config:
        from_attributes = True
