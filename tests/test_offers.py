import pytest
from uuid import uuid4
from sqlalchemy import select
from datetime import datetime, timezone, timedelta
from app.models import Offer, Enterprise, Application, Candidate, Position
from app.schemas.offer import OfferCreate, OfferSend


@pytest.mark.asyncio
async def test_create_offer(db_session, test_user, test_tenant):
    """Test creating an offer from an application."""
    # Setup: Create position with enterprise
    enterprise = Enterprise(
        tenant_id=test_tenant.id,
        name="Test Company",
        created_by=test_user.id,
    )
    db_session.add(enterprise)
    await db_session.commit()

    position = Position(
        tenant_id=test_tenant.id,
        enterprise_id=enterprise.id,
        title="Software Engineer",
        created_by=test_user.id,
    )
    db_session.add(position)
    await db_session.commit()

    candidate = Candidate(
        tenant_id=test_tenant.id,
        email="test@example.com",
        first_name="John",
        last_name="Doe",
    )
    db_session.add(candidate)
    await db_session.commit()

    application = Application(
        tenant_id=test_tenant.id,
        candidate_id=candidate.id,
        position_id=position.id,
    )
    db_session.add(application)
    await db_session.commit()

    # Create offer
    data = OfferCreate(
        salary_min=50000,
        salary_max=70000,
        currency="EUR",
        contract_type="permanent",
    )

    offer = Offer(
        tenant_id=test_tenant.id,
        enterprise_id=enterprise.id,
        application_id=application.id,
        **data.model_dump(),
        created_by=test_user.id,
        status="draft",
    )
    db_session.add(offer)
    await db_session.commit()
    await db_session.refresh(offer)

    assert offer.id is not None
    assert offer.status == "draft"
    assert offer.salary_min == 50000
    assert offer.salary_max == 70000


@pytest.mark.asyncio
async def test_offer_workflow(db_session, test_user, test_tenant):
    """Test offer status workflow: draft -> sent -> signed."""
    enterprise = Enterprise(
        tenant_id=test_tenant.id,
        name="Test Company",
        created_by=test_user.id,
    )
    db_session.add(enterprise)
    await db_session.commit()

    position = Position(
        tenant_id=test_tenant.id,
        enterprise_id=enterprise.id,
        title="Software Engineer",
        created_by=test_user.id,
    )
    db_session.add(position)
    await db_session.commit()

    candidate = Candidate(
        tenant_id=test_tenant.id,
        email="test@example.com",
        first_name="John",
        last_name="Doe",
    )
    db_session.add(candidate)
    await db_session.commit()

    application = Application(
        tenant_id=test_tenant.id,
        candidate_id=candidate.id,
        position_id=position.id,
    )
    db_session.add(application)
    await db_session.commit()

    offer = Offer(
        tenant_id=test_tenant.id,
        enterprise_id=enterprise.id,
        application_id=application.id,
        salary_min=50000,
        currency="EUR",
        contract_type="permanent",
        created_by=test_user.id,
    )
    db_session.add(offer)
    await db_session.commit()

    # Transition: draft -> sent
    offer.status = "sent"
    offer.sent_at = datetime.now(timezone.utc)
    offer.signature_token = "test_token_123"
    offer.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    await db_session.commit()
    await db_session.refresh(offer)

    assert offer.status == "sent"
    assert offer.signature_token == "test_token_123"

    # Transition: sent -> signed
    offer.status = "signed"
    offer.signed_at = datetime.now(timezone.utc)
    offer.signed_by = test_user.id
    await db_session.commit()
    await db_session.refresh(offer)

    assert offer.status == "signed"
    assert offer.signed_by == test_user.id


@pytest.mark.asyncio
async def test_offer_rejection(db_session, test_user, test_tenant):
    """Test offer rejection workflow."""
    enterprise = Enterprise(
        tenant_id=test_tenant.id,
        name="Test Company",
        created_by=test_user.id,
    )
    db_session.add(enterprise)
    await db_session.commit()

    position = Position(
        tenant_id=test_tenant.id,
        enterprise_id=enterprise.id,
        title="Software Engineer",
        created_by=test_user.id,
    )
    db_session.add(position)
    await db_session.commit()

    candidate = Candidate(
        tenant_id=test_tenant.id,
        email="test@example.com",
        first_name="John",
        last_name="Doe",
    )
    db_session.add(candidate)
    await db_session.commit()

    application = Application(
        tenant_id=test_tenant.id,
        candidate_id=candidate.id,
        position_id=position.id,
    )
    db_session.add(application)
    await db_session.commit()

    offer = Offer(
        tenant_id=test_tenant.id,
        enterprise_id=enterprise.id,
        application_id=application.id,
        salary_min=50000,
        currency="EUR",
        contract_type="permanent",
        created_by=test_user.id,
        status="sent",
    )
    db_session.add(offer)
    await db_session.commit()

    # Reject offer
    offer.status = "rejected"
    offer.rejected_at = datetime.now(timezone.utc)
    offer.rejection_reason = "Candidate declined"
    await db_session.commit()
    await db_session.refresh(offer)

    assert offer.status == "rejected"
    assert offer.rejection_reason == "Candidate declined"


@pytest.mark.asyncio
async def test_offer_tenant_isolation(db_session, test_user, test_tenant):
    """Test that offers are isolated by tenant."""
    from app.models import Tenant

    # Create enterprise and offer in test_tenant
    enterprise1 = Enterprise(
        tenant_id=test_tenant.id,
        name="Company A",
        created_by=test_user.id,
    )
    db_session.add(enterprise1)
    await db_session.commit()

    # Setup offer1
    position1 = Position(
        tenant_id=test_tenant.id,
        enterprise_id=enterprise1.id,
        title="Role 1",
        created_by=test_user.id,
    )
    candidate1 = Candidate(
        tenant_id=test_tenant.id,
        email="test1@example.com",
        first_name="John",
        last_name="Doe",
    )
    db_session.add_all([position1, candidate1])
    await db_session.commit()

    app1 = Application(
        tenant_id=test_tenant.id,
        candidate_id=candidate1.id,
        position_id=position1.id,
    )
    db_session.add(app1)
    await db_session.commit()

    offer1 = Offer(
        tenant_id=test_tenant.id,
        enterprise_id=enterprise1.id,
        application_id=app1.id,
        currency="EUR",
        contract_type="permanent",
        created_by=test_user.id,
    )
    db_session.add(offer1)
    await db_session.commit()

    # Create different tenant with offer
    other_tenant = Tenant(name="Other Tenant")
    db_session.add(other_tenant)
    await db_session.commit()

    enterprise2 = Enterprise(
        tenant_id=other_tenant.id,
        name="Company B",
        created_by=test_user.id,
    )
    db_session.add(enterprise2)
    await db_session.commit()

    # Query as test_tenant
    result = await db_session.execute(
        select(Offer).where(Offer.tenant_id == test_tenant.id)
    )
    offers = result.scalars().all()

    assert len(offers) == 1
    assert offers[0].enterprise_id == enterprise1.id
