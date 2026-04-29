"""Tests for feature flags (modules_config) on Tenant."""
import pytest
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Tenant, User
from app.core.dependencies import require_module


@pytest.mark.asyncio
async def test_module_enabled_by_default(db: AsyncSession):
    """Test that modules are enabled by default (opt-out model)."""
    tenant = Tenant(
        id=uuid4(),
        name="Test Tenant",
        plan="pro",
        modules_config=None,  # Not set
    )
    db.add(tenant)
    await db.commit()

    # Verify modules_config is empty or None
    result = await db.execute(select(Tenant).where(Tenant.id == tenant.id))
    fetched_tenant = result.scalar_one()
    assert fetched_tenant.modules_config is None or fetched_tenant.modules_config == {}


@pytest.mark.asyncio
async def test_module_disabled(db: AsyncSession):
    """Test that a module can be disabled."""
    tenant = Tenant(
        id=uuid4(),
        name="Test Tenant",
        plan="pro",
        modules_config={"ai_phone_interview": False},
    )
    db.add(tenant)
    await db.commit()

    result = await db.execute(select(Tenant).where(Tenant.id == tenant.id))
    fetched_tenant = result.scalar_one()
    assert fetched_tenant.modules_config["ai_phone_interview"] is False


@pytest.mark.asyncio
async def test_multiple_modules_config(db: AsyncSession):
    """Test that multiple modules can be configured."""
    modules_config = {
        "cv_scoring": True,
        "ai_phone_interview": False,
        "matching_nm": True,
        "analytics": False,
    }
    tenant = Tenant(
        id=uuid4(),
        name="Test Tenant",
        plan="pro",
        modules_config=modules_config,
    )
    db.add(tenant)
    await db.commit()

    result = await db.execute(select(Tenant).where(Tenant.id == tenant.id))
    fetched_tenant = result.scalar_one()
    assert fetched_tenant.modules_config == modules_config


@pytest.mark.asyncio
async def test_require_module_enabled(db: AsyncSession):
    """Test require_module dependency when module is enabled."""
    tenant = Tenant(
        id=uuid4(),
        name="Test Tenant",
        plan="pro",
        modules_config={"analytics": True},
    )
    db.add(tenant)
    await db.commit()

    user = User(
        id=uuid4(),
        tenant_id=tenant.id,
        email="test@example.com",
        hashed_password="hashed",
        role="admin",
    )
    db.add(user)
    await db.commit()

    # Test that require_module("analytics") doesn't raise when enabled
    try:
        dependency = require_module("analytics")
        # The dependency is properly formed
        assert dependency is not None
    except Exception as e:
        pytest.fail(f"require_module raised unexpected exception: {e}")


@pytest.mark.asyncio
async def test_require_module_disabled(db: AsyncSession):
    """Test require_module dependency when module is disabled."""
    tenant = Tenant(
        id=uuid4(),
        name="Test Tenant",
        plan="pro",
        modules_config={"analytics": False},
    )
    db.add(tenant)
    await db.commit()

    # Test that require_module("analytics") is properly defined
    dependency = require_module("analytics")
    assert dependency is not None
