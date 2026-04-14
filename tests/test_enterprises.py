import pytest
from uuid import uuid4
from sqlalchemy import select
from app.models import Enterprise, Tenant, User
from app.schemas.enterprise import EnterpriseCreate


@pytest.mark.asyncio
async def test_create_enterprise(db_session, test_user, test_tenant):
    """Test creating a new enterprise."""
    data = EnterpriseCreate(
        name="Test Company",
        industry="Tech",
        domain="test.com",
        contact_email="contact@test.com",
        contact_phone="+1234567890",
        address="123 Test St",
    )

    enterprise = Enterprise(
        tenant_id=test_tenant.id,
        created_by=test_user.id,
        **data.model_dump(),
    )
    db_session.add(enterprise)
    await db_session.commit()
    await db_session.refresh(enterprise)

    assert enterprise.id is not None
    assert enterprise.name == "Test Company"
    assert enterprise.industry == "Tech"
    assert enterprise.status == "active"


@pytest.mark.asyncio
async def test_enterprise_relationships(db_session, test_user, test_tenant):
    """Test enterprise relationships with positions and offers."""
    enterprise = Enterprise(
        tenant_id=test_tenant.id,
        name="Multi-Client Agency",
        created_by=test_user.id,
    )
    db_session.add(enterprise)
    await db_session.commit()
    await db_session.refresh(enterprise)

    # Verify relationships exist
    assert enterprise.tenant_id == test_tenant.id
    assert enterprise.created_by == test_user.id
    assert enterprise.positions == []
    assert enterprise.offers == []


@pytest.mark.asyncio
async def test_list_enterprises(db_session, test_user, test_tenant):
    """Test listing enterprises for a tenant."""
    # Create 3 enterprises
    for i in range(3):
        enterprise = Enterprise(
            tenant_id=test_tenant.id,
            name=f"Company {i+1}",
            created_by=test_user.id,
        )
        db_session.add(enterprise)

    await db_session.commit()

    # Query
    result = await db_session.execute(
        select(Enterprise).where(Enterprise.tenant_id == test_tenant.id)
    )
    enterprises = result.scalars().all()

    assert len(enterprises) == 3


@pytest.mark.asyncio
async def test_update_enterprise(db_session, test_user, test_tenant):
    """Test updating an enterprise."""
    enterprise = Enterprise(
        tenant_id=test_tenant.id,
        name="Old Name",
        industry="Tech",
        created_by=test_user.id,
    )
    db_session.add(enterprise)
    await db_session.commit()

    # Update
    enterprise.name = "New Name"
    enterprise.industry = "Finance"
    await db_session.commit()
    await db_session.refresh(enterprise)

    assert enterprise.name == "New Name"
    assert enterprise.industry == "Finance"


@pytest.mark.asyncio
async def test_delete_enterprise_soft(db_session, test_user, test_tenant):
    """Test soft delete (archive) of an enterprise."""
    enterprise = Enterprise(
        tenant_id=test_tenant.id,
        name="To Archive",
        created_by=test_user.id,
    )
    db_session.add(enterprise)
    await db_session.commit()
    enterprise_id = enterprise.id

    # Soft delete
    enterprise.status = "archived"
    await db_session.commit()

    # Verify
    result = await db_session.get(Enterprise, enterprise_id)
    assert result.status == "archived"


@pytest.mark.asyncio
async def test_enterprise_tenant_isolation(db_session, test_user, test_tenant):
    """Test that enterprises are isolated by tenant."""
    # Create enterprise in test_tenant
    enterprise1 = Enterprise(
        tenant_id=test_tenant.id,
        name="Company A",
        created_by=test_user.id,
    )
    db_session.add(enterprise1)

    # Create another tenant
    other_tenant = Tenant(name="Other Tenant")
    db_session.add(other_tenant)
    await db_session.commit()

    # Create enterprise in other_tenant
    enterprise2 = Enterprise(
        tenant_id=other_tenant.id,
        name="Company B",
        created_by=test_user.id,
    )
    db_session.add(enterprise2)
    await db_session.commit()

    # Query as test_tenant
    result = await db_session.execute(
        select(Enterprise).where(Enterprise.tenant_id == test_tenant.id)
    )
    enterprises = result.scalars().all()

    assert len(enterprises) == 1
    assert enterprises[0].name == "Company A"
