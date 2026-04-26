"""Email sequences automatisees — Phase 2.2 V1_ROADMAP.

Modele : EmailSequence (declencheur + ordre des etapes) + SequenceStep (delay + template).

Triggers supportes :
- candidate.rejected : ex. envoyer email politely 24h apres
- candidate.invited  : reminder 48h avant l'entretien
- offer.signed       : onboarding email J+1
- pipeline.stale     : relance candidat 7j apres son dernier mouvement

L'execution reelle se fait via Celery worker (process_sequence_step) qui
scanne les enrolments dus.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EmailSequence(Base):
    __tablename__ = "email_sequences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger: Mapped[str] = mapped_column(String(50), index=True)  # candidate.rejected, candidate.invited, offer.signed, pipeline.stale
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    steps = relationship(
        "SequenceStep",
        back_populates="sequence",
        cascade="all, delete-orphan",
        order_by="SequenceStep.order_index",
    )


class SequenceStep(Base):
    __tablename__ = "sequence_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sequence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_sequences.id", ondelete="CASCADE"), index=True
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_templates.id", ondelete="RESTRICT")
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    delay_hours: Mapped[int] = mapped_column(Integer, default=24)  # delai depuis trigger ou step precedent

    sequence = relationship("EmailSequence", back_populates="steps")
    template = relationship("EmailTemplate")


class SequenceEnrollment(Base):
    """Enrolement d'un candidat dans une sequence — instance d'execution."""

    __tablename__ = "sequence_enrollments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    sequence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_sequences.id", ondelete="CASCADE")
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    current_step_index: Mapped[int] = mapped_column(Integer, default=0)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    # active | completed | canceled | failed
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
