"""Commentaires multi-utilisateurs sur une fiche candidat.

Permet aux membres de l'équipe (recruteurs, hiring managers) d'échanger
autour d'un candidat : questions, validations, doutes, contexte historique.

Supporte :
- threads (parent_id self-FK)
- mentions @user (mentioned_user_ids JSONB → notifications futures)
- édition (edited_at)
- soft delete (deleted_at) — préserve l'historique pour audit AI Act
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CandidateComment(Base):
    __tablename__ = "candidate_comments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_comments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    content: Mapped[str] = mapped_column(Text)
    # Liste d'IDs utilisateurs mentionnés (@). Stockée en JSONB pour requêtes
    # futures du type "comments mentioning me". Les @ sont parsés côté
    # serveur depuis content au moment du POST/PATCH.
    mentioned_user_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Relationships
    candidate = relationship("Candidate")
    author = relationship("User", foreign_keys=[author_id])
    parent = relationship("CandidateComment", remote_side=[id], foreign_keys=[parent_id])
