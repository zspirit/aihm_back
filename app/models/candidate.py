import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    position_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("positions.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cv_file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cv_parsed_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cv_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    cv_score_explanation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    pipeline_status: Mapped[str] = mapped_column(String(50), default="new")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Profile fields (intrinseque, pas lie a un poste)
    profile_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    profile_score_explanation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    profile_competencies: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Structure: {
    #   "technical": [{"name": "Python", "level": 4, "normalized": "python", "demonstrated": true}],
    #   "experience": [{"title": "Dev Senior", "company": "X", "duration_months": 24, "responsibilities": [...]}],
    #   "education": [{"degree": "Master", "field": "CS", "institution": "..."}],
    #   "languages": [{"name": "Francais", "level": "natif"}],
    #   "soft_skills": ["Leadership", "Communication"]
    # }
    profile_suggestions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Structure: {"suggestions": [...], "cv_quality_score": 65, "cv_quality_details": {...}}
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Resume IA (cache)
    summary_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Feedback candidat
    feedback_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    feedback_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Anonymisation
    is_anonymized: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # Phase 4.2 V1_ROADMAP — DEI opt-in (cf. migration e1f2a4b5c6d7)
    # Tous nullable / opt-in : RGPD-compliant. Anonymisés avant scoring.
    dei_consent: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    gender: Mapped[str | None] = mapped_column(String(30), nullable=True)
    age_range: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 18-25, 26-35, ...
    nationality: Mapped[str | None] = mapped_column(String(50), nullable=True)
    disability_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    position = relationship("Position", back_populates="candidates")
    consents = relationship("Consent", back_populates="candidate", cascade="all, delete-orphan")
    interviews = relationship("Interview", back_populates="candidate", cascade="all, delete-orphan")
    applications = relationship("Application", back_populates="candidate", cascade="all, delete-orphan")
