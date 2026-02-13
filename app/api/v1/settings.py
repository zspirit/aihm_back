from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_role
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.tenant import TenantSettings, TenantSettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


def _tenant_to_response(tenant: Tenant) -> TenantSettings:
    return TenantSettings(
        id=str(tenant.id),
        name=tenant.name,
        plan=tenant.plan,
        logo_url=tenant.logo_url,
        website=tenant.website,
        primary_color=tenant.primary_color,
        timezone=tenant.timezone,
        data_retention_days=tenant.data_retention_days,
        max_interview_duration=tenant.max_interview_duration,
    )


@router.get("", response_model=TenantSettings)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    tenant = await db.get(Tenant, user.tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return _tenant_to_response(tenant)


@router.patch("", response_model=TenantSettings)
async def update_settings(
    data: TenantSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    tenant = await db.get(Tenant, user.tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(tenant, field, value)

    await db.flush()
    await db.refresh(tenant)
    return _tenant_to_response(tenant)
