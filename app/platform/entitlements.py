"""Module entitlements — 'does this tenant have this module activated?'.

Single source of truth that drives both feature-flags and (future) billing.
Checks the platform ``tenant_entitlements`` table first, then falls back to the
legacy ``Tenant.modules_config`` opt-out flags (consistent with the existing
``app.core.dependencies.require_module``) so nothing breaks during migration.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entitlement import TenantEntitlement
from app.models.tenant import Tenant


async def is_module_enabled(
    db: AsyncSession, tenant_id: uuid.UUID, module_key: str
) -> bool:
    res = await db.execute(
        select(TenantEntitlement).where(
            TenantEntitlement.tenant_id == tenant_id,
            TenantEntitlement.module_key == module_key,
        )
    )
    ent = res.scalar_one_or_none()
    if ent is not None:
        return ent.status == "active"

    # Fallback: legacy opt-out flags (default enabled).
    tenant = await db.get(Tenant, tenant_id)
    modules = (tenant.modules_config or {}) if tenant else {}
    return bool(modules.get(module_key, True))
