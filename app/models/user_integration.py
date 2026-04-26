"""User integrations (OAuth tokens, API keys) — Phase 2.3 V1_ROADMAP.

Stocke les tokens OAuth chiffres pour Google Calendar / Microsoft Outlook.
Le chiffrement reel doit utiliser settings.ENCRYPTION_KEY (Fernet) — laisse
nul en v0.0.1 cote storage, le helper services/integrations.py gere le
chiffrement/dechiffrement.

Provider supportes (en plan):
- google_calendar
- microsoft_calendar
- linkedin (future Phase 3.2)
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column


from app.core.database import Base


class UserIntegration(Base):
    __tablename__ = "user_integrations"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_user_provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(50))  # google_calendar | microsoft_calendar
    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    account_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # active | revoked | expired
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
