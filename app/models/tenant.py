import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255))
    plan: Mapped[str] = mapped_column(String(50), default="free")
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    website: Mapped[str | None] = mapped_column(String(255), nullable=True)
    primary_color: Mapped[str] = mapped_column(String(7), default="#4F46E5")
    timezone: Mapped[str] = mapped_column(String(50), default="Africa/Casablanca")
    data_retention_days: Mapped[int] = mapped_column(Integer, default=180)
    max_interview_duration: Mapped[int] = mapped_column(Integer, default=600)

    # Scoring weights (0-100, must sum to 100)
    scoring_skills_weight: Mapped[int] = mapped_column(Integer, default=50)
    scoring_experience_weight: Mapped[int] = mapped_column(Integer, default=30)
    scoring_education_weight: Mapped[int] = mapped_column(Integer, default=20)

    # Compliance framework
    compliance_framework: Mapped[str] = mapped_column(String(50), default="CNDP")
    compliance_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Feature flags per module, e.g. {"ai_phone_interview": false}
    modules_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default={})

    # Phase 3.1 — Career page publique
    public_career_page: Mapped[bool] = mapped_column(default=False)
    public_slug: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    public_branding: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    users = relationship("User", back_populates="tenant")
    positions = relationship("Position", back_populates="tenant")
    enterprises = relationship("Enterprise", back_populates="tenant")
    skills = relationship("Skill", back_populates="tenant")
