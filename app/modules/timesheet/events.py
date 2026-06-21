"""Timesheet module — event handlers.

POC seam: when the ATS marks a candidate as *hired*, the timesheet module turns
that person into a CONSULTANT — but only if the tenant has the ``timesheet``
module entitled. Demonstrates the three platform mechanisms at once:
People/Party unification, the event bus, and entitlement gating.
"""
from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.party import Party, PartyFacet
from app.platform.entitlements import is_module_enabled

logger = structlog.get_logger(__name__)

MODULE_KEY = "timesheet"


async def on_candidate_hired(
    *, payload: dict, db: AsyncSession, tenant_id: uuid.UUID
) -> None:
    if not await is_module_enabled(db, tenant_id, MODULE_KEY):
        logger.info(
            "timesheet_off_skip_consultant",
            tenant_id=str(tenant_id),
            candidate_id=payload.get("candidate_id"),
        )
        return

    party = await _get_or_create_party(db, tenant_id, payload)
    await _ensure_facet(db, party.id, "candidate", "ats", {"candidate_id": payload.get("candidate_id")})
    await _ensure_facet(
        db,
        party.id,
        "consultant",
        MODULE_KEY,
        {"kind": "employee", "source": "ats_hire", "candidate_id": payload.get("candidate_id")},
    )
    await db.flush()
    logger.info(
        "consultant_facet_created_from_hire",
        party_id=str(party.id),
        candidate_id=payload.get("candidate_id"),
    )


async def _get_or_create_party(db: AsyncSession, tenant_id: uuid.UUID, payload: dict) -> Party:
    candidate_id = payload.get("candidate_id")
    if candidate_id:
        res = await db.execute(
            select(Party)
            .join(PartyFacet, PartyFacet.party_id == Party.id)
            .where(
                Party.tenant_id == tenant_id,
                PartyFacet.facet == "candidate",
                PartyFacet.data["candidate_id"].astext == str(candidate_id),
            )
        )
        existing = res.scalars().first()
        if existing:
            return existing

    party = Party(
        tenant_id=tenant_id,
        kind="person",
        display_name=payload.get("name") or "Sans nom",
        emails=[payload["email"]] if payload.get("email") else [],
    )
    db.add(party)
    await db.flush()
    return party


async def _ensure_facet(
    db: AsyncSession, party_id: uuid.UUID, facet: str, module_key: str, data: dict
) -> None:
    res = await db.execute(
        select(PartyFacet).where(PartyFacet.party_id == party_id, PartyFacet.facet == facet)
    )
    if res.scalar_one_or_none() is not None:
        return
    db.add(PartyFacet(party_id=party_id, facet=facet, module_key=module_key, data=data))
