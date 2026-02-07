import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    position_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("positions.id"))
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

    position = relationship("Position", back_populates="candidates")
    consents = relationship("Consent", back_populates="candidate")
    interviews = relationship("Interview", back_populates="candidate")
