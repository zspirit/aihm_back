"""Shortlists partagees — listes de candidats curees par equipe.

Phase 1.2 du V1_ROADMAP. Permet a un recruteur/hiring manager de creer
une selection nommee de candidats (ex: "Top 5 backend Python", "A presenter
au CTO") et de la partager avec ses coequipiers.

Design :
- Shortlist : entite haut-niveau (nom, description, owner, tenant_id, position_id optionnel)
- ShortlistCandidate : table M2M shortlist <-> candidate avec ordre + note libre

Le partage avec les coequipiers est implicite : tout user du meme tenant
voit les shortlists du tenant. Possibilite d'ajouter un champ `is_private`
dans une iteration future pour des shortlists prive owner-only.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Shortlist(Base):
    __tablename__ = "shortlists"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    # Optionnel : si la shortlist est dediee a un poste (ex: "Top 5 pour Data Engineer")
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("positions.id", ondelete="SET NULL"), nullable=True, index=True
    )

    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    position = relationship("Position", foreign_keys=[position_id])
    items = relationship(
        "ShortlistCandidate",
        back_populates="shortlist",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ShortlistCandidate(Base):
    __tablename__ = "shortlist_candidates"
    __table_args__ = (
        UniqueConstraint("shortlist_id", "candidate_id", name="uq_shortlist_candidate"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    shortlist_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shortlists.id", ondelete="CASCADE"), index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    added_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    position: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    shortlist = relationship("Shortlist", back_populates="items")
    candidate = relationship("Candidate")
