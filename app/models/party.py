import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Party(Base):
    """Unified person/org record shared across all modules.

    A candidate (ATS), a consultant (Timesheet) and an employee (HR) are
    *facets* of the same Party — one record, one history — instead of three
    tables that resync. See ADR-05.
    """

    __tablename__ = "parties"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    kind: Mapped[str] = mapped_column(String(20), default="person")  # person | org
    display_name: Mapped[str] = mapped_column(String(255))
    emails: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    facets = relationship("PartyFacet", back_populates="party", cascade="all, delete-orphan")


class PartyFacet(Base):
    """A role a Party plays, contributed by a module."""

    __tablename__ = "party_facets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    party_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("parties.id"))
    facet: Mapped[str] = mapped_column(String(40))  # candidate | consultant | employee | client_contact | user
    module_key: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    party = relationship("Party", back_populates="facets")
