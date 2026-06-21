import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TenantEntitlement(Base):
    """Which module a tenant has activated.

    Platform source of truth that drives feature-flags AND billing (the
    foundation of 'pay as you go / grow / want'). Supersedes the legacy
    ``Tenant.modules_config`` opt-out flags over time. See ADR-05.
    """

    __tablename__ = "tenant_entitlements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    module_key: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | trial | suspended
    plan: Mapped[str | None] = mapped_column(String(40), nullable=True)
    seats: Mapped[int | None] = mapped_column(Integer, nullable=True)
    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
