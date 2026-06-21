"""POC plateforme modulaire (ADR-01/ADR-05).

Valide les trois coutures du socle sur le code existant :
1. Event bus inter-modules (ATS émet -> Timesheet réagit).
2. People/Party unifié (candidat + consultant = facettes d'une même personne).
3. Entitlements (le consultant n'est créé que si le module timesheet est activé).
"""
import uuid

import pytest
from sqlalchemy import select

from app.models.domain_event import DomainEvent
from app.models.entitlement import TenantEntitlement
from app.models.party import Party, PartyFacet
from app.models.tenant import Tenant
from app.platform.bootstrap import register_modules
from app.platform.events import event_bus

# Wire the timesheet module's handlers (subscribe-on-import); idempotent.
register_modules()


async def _hire(db, tenant_id, name="Karim B.", email="karim@example.io"):
    await event_bus.emit(
        "ats.candidate.hired",
        payload={"candidate_id": str(uuid.uuid4()), "name": name, "email": email},
        db=db,
        tenant_id=tenant_id,
        source_module="ats",
    )
    await db.flush()


@pytest.mark.asyncio
async def test_hire_creates_consultant_when_timesheet_enabled(db_session):
    tenant = Tenant(name="ESN Test")
    db_session.add(tenant)
    await db_session.flush()

    await _hire(db_session, tenant.id)

    parties = (
        await db_session.execute(select(Party).where(Party.tenant_id == tenant.id))
    ).scalars().all()
    assert len(parties) == 1, "une Party unique doit être créée pour l'embauché"

    facets = {
        f.facet
        for f in (
            await db_session.execute(
                select(PartyFacet).where(PartyFacet.party_id == parties[0].id)
            )
        ).scalars().all()
    }
    # Candidat ET consultant sont des facettes de la MÊME personne.
    assert facets == {"candidate", "consultant"}

    events = (
        await db_session.execute(
            select(DomainEvent).where(DomainEvent.tenant_id == tenant.id)
        )
    ).scalars().all()
    assert any(e.type == "ats.candidate.hired" for e in events), "event loggé"


@pytest.mark.asyncio
async def test_hire_skips_consultant_when_timesheet_disabled(db_session):
    tenant = Tenant(name="ESN NoTime")
    db_session.add(tenant)
    await db_session.flush()
    db_session.add(
        TenantEntitlement(tenant_id=tenant.id, module_key="timesheet", status="suspended")
    )
    await db_session.flush()

    await _hire(db_session, tenant.id, name="Sofia", email="sofia@example.io")

    # Module désactivé -> le handler sort avant toute écriture métier.
    parties = (
        await db_session.execute(select(Party).where(Party.tenant_id == tenant.id))
    ).scalars().all()
    assert parties == [], "aucune Party/consultant si le module timesheet est suspendu"

    # L'event reste tout de même journalisé (traçabilité).
    events = (
        await db_session.execute(
            select(DomainEvent).where(DomainEvent.tenant_id == tenant.id)
        )
    ).scalars().all()
    assert len(events) == 1


@pytest.mark.asyncio
async def test_hire_is_idempotent(db_session):
    """Deux 'hired' sur le même candidat ne dupliquent pas la personne ni la facette."""
    tenant = Tenant(name="ESN Idem")
    db_session.add(tenant)
    await db_session.flush()

    candidate_id = str(uuid.uuid4())
    payload = {"candidate_id": candidate_id, "name": "Yanis", "email": "yanis@example.io"}
    for _ in range(2):
        await event_bus.emit(
            "ats.candidate.hired",
            payload=payload,
            db=db_session,
            tenant_id=tenant.id,
            source_module="ats",
        )
        await db_session.flush()

    parties = (
        await db_session.execute(select(Party).where(Party.tenant_id == tenant.id))
    ).scalars().all()
    assert len(parties) == 1

    consultant_facets = [
        f
        for f in (
            await db_session.execute(
                select(PartyFacet).where(PartyFacet.party_id == parties[0].id)
            )
        ).scalars().all()
        if f.facet == "consultant"
    ]
    assert len(consultant_facets) == 1
