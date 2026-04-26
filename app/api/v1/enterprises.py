"""Enterprise CRUD endpoints (Phase 3)."""
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import selectinload

from app.core.dependencies import get_db, get_current_user
from app.models import Enterprise, User
from app.schemas.enterprise import (
    EnterpriseCreate,
    EnterpriseUpdate,
    EnterpriseResponse,
    EnterpriseFull,
)

router = APIRouter(prefix="/enterprises", tags=["enterprises"])


@router.get("", response_model=list[EnterpriseResponse])
async def list_enterprises(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
):
    """List all enterprises for the tenant."""
    query = select(Enterprise).where(
        Enterprise.tenant_id == current_user.tenant_id
    ).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("", response_model=EnterpriseFull, status_code=201)
async def create_enterprise(
    payload: EnterpriseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new enterprise."""
    enterprise = Enterprise(
        tenant_id=current_user.tenant_id,
        **payload.model_dump(),
        created_by=current_user.id,
    )
    db.add(enterprise)
    await db.commit()
    await db.refresh(enterprise)
    return enterprise


@router.get("/{enterprise_id}", response_model=EnterpriseFull)
async def get_enterprise(
    enterprise_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific enterprise."""
    enterprise = await db.get(Enterprise, enterprise_id)
    if not enterprise or enterprise.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    return enterprise


@router.put("/{enterprise_id}", response_model=EnterpriseFull)
async def update_enterprise(
    enterprise_id: UUID,
    payload: EnterpriseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an enterprise."""
    enterprise = await db.get(Enterprise, enterprise_id)
    if not enterprise or enterprise.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(enterprise, field, value)

    await db.commit()
    await db.refresh(enterprise)
    return enterprise


@router.delete("/{enterprise_id}", status_code=204)
async def delete_enterprise(
    enterprise_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete (archive) an enterprise."""
    enterprise = await db.get(Enterprise, enterprise_id)
    if not enterprise or enterprise.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    # Soft delete: mark as archived
    enterprise.status = "archived"
    await db.commit()
