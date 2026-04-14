import uuid
from datetime import datetime, timezone
from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    candidate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"))
    position_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("positions.id", ondelete="CASCADE"))

    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_score_explanation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    pipeline_status: Mapped[str] = mapped_column(String(50), default="new")
    decision: Mapped[str | None] = mapped_column(String(50), nullable=True)  # accepted / rejected / pending
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    candidate = relationship("Candidate", back_populates="applications")
    position = relationship("Position", back_populates="applications")
    offers = relationship("Offer", back_populates="application", cascade="all, delete-orphan")
