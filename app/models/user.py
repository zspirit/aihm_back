import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="recruiter")
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # Phase 4.3 V1_ROADMAP — referral link personnel (cf. migration e1f2a4b5c6d7)
    referral_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    tenant = relationship("Tenant", back_populates="users")
    password_reset_tokens = relationship("PasswordResetToken", back_populates="user")
    email_verification_tokens = relationship("EmailVerificationToken", back_populates="user")
