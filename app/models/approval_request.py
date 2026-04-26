"""Approval requests — workflows de validation entre coequipiers.

Phase 1.3 du V1_ROADMAP. Modele generique : un utilisateur (requester) demande
une validation a un autre (approver) sur une decision liee a une entite donnee.

Use cases :
- "Cette offre a 90k EUR depasse mon plafond, validation CFO requise" (entity_type='offer')
- "Je veux rejeter ce candidat malgre son score 88, peux-tu valider ?" (entity_type='application')
- "Publication poste senior X" (entity_type='position')

L'identification de l'entite est generique (entity_type + entity_id) pour rester
extensible sans changer le modele a chaque nouveau use case.

Statuts :
- pending   : en attente de decision
- approved  : approuve par approver
- rejected  : refuse par approver
- canceled  : annule par requester avant decision
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), index=True
    )
    requester_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    approver_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), index=True
    )

    entity_type: Mapped[str] = mapped_column(String(50))  # offer, application, position, ...
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)

    title: Mapped[str] = mapped_column(String(200))
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)

    # pending | approved | rejected | canceled
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    requester = relationship("User", foreign_keys=[requester_id])
    approver = relationship("User", foreign_keys=[approver_id])
