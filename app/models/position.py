import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class PositionLevel(str, enum.Enum):
    """Niveau hiérarchique du poste (axe orthogonal à seniority_level).

    - junior / mid / senior : contributeurs individuels
    - lead : réfèrent technique / coordination d'équipe
    - manager : responsable d'équipe (people management)
    - executive : direction / C-level
    """

    junior = "junior"
    mid = "mid"
    senior = "senior"
    lead = "lead"
    manager = "manager"
    executive = "executive"


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    enterprise_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    required_skills: Mapped[dict] = mapped_column(JSONB, default=list)
    seniority_level: Mapped[str] = mapped_column(String(50), default="mid")
    level: Mapped[PositionLevel | None] = mapped_column(
        Enum(PositionLevel, name="position_level"), nullable=True
    )
    sla_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    custom_questions: Mapped[dict] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(50), default="draft")
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_advance_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auto_reject_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    tenant = relationship("Tenant", back_populates="positions")
    enterprise = relationship("Enterprise", back_populates="positions")
    candidates = relationship("Candidate", back_populates="position")
    applications = relationship(
        "Application", back_populates="position", cascade="all, delete-orphan"
    )
