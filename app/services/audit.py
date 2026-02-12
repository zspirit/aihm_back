"""Audit logging service — records sensitive actions for compliance."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def log_action(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID | None = None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    details: dict | None = None,
):
    """Write an audit log entry. Fire-and-forget, never raises."""
    try:
        entry = AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
        )
        db.add(entry)
    except Exception:
        pass
