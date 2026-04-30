"""Psychometric assessment — Phase 4.1 V1_ROADMAP.

Lightweight 5-question post-interview assessment scored on 5 dimensions:
- communication
- problem_solving
- team_fit
- stress_handling
- leadership

Each dimension carries a 1–5 raw score (recruiter-graded or self-reported).
After insertion, an async Claude analysis populates `traits_json` and
`turnover_risk` for the recruiter dashboard. Both fields are nullable so
the row is usable immediately even if the LLM call hasn't returned yet.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PsychometricAssessment(Base):
    __tablename__ = "psychometric_assessments"
    __table_args__ = (
        UniqueConstraint("interview_id", name="uq_psycho_interview"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), index=True
    )
    interview_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interviews.id", ondelete="CASCADE"), index=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="CASCADE"), index=True
    )
    submitted_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )

    # 1–5 scale on 5 dimensions
    score_communication: Mapped[int] = mapped_column(Integer)
    score_problem_solving: Mapped[int] = mapped_column(Integer)
    score_team_fit: Mapped[int] = mapped_column(Integer)
    score_stress_handling: Mapped[int] = mapped_column(Integer)
    score_leadership: Mapped[int] = mapped_column(Integer)

    # Filled by the Claude follow-up. Nullable until the LLM returns.
    traits_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 'low' | 'medium' | 'high' | None
    turnover_risk: Mapped[str | None] = mapped_column(String(10), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
