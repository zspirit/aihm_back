"""Email templates + logs — Phase 2.1 V1_ROADMAP.

EmailTemplate : modeles Markdown reutilisables avec variables {{var}}.
EmailLog : trace d'envoi (qui, quand, status, provider id).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EmailTemplate(Base):
    __tablename__ = "email_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    # Type fonctionnel : invitation, rejection, offer_followup, generic, ...
    type: Mapped[str] = mapped_column(String(50), default="generic", index=True)
    subject: Mapped[str] = mapped_column(String(500))
    body_markdown: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailLog(Base):
    __tablename__ = "email_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_templates.id", ondelete="SET NULL"), nullable=True
    )
    sent_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    to_email: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(500))
    body_rendered: Mapped[str] = mapped_column(Text)
    variables: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # queued | sent | failed
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)  # smtp | sendgrid | mailgun | console
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    template = relationship("EmailTemplate", foreign_keys=[template_id])
    candidate = relationship("Candidate", foreign_keys=[candidate_id])
