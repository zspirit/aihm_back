"""Tests for consent endpoints: GET/POST /api/v1/consent/{token}."""
import secrets
import uuid

import pytest
import pytest_asyncio
from app.models.candidate import Candidate
from app.models.consent import Consent
from app.models.position import Position
from app.models.tenant import Tenant
from app.models.user import User
from app.core.security import hash_password

from tests.conftest import TestSession


@pytest_asyncio.fixture()
async def seed(_setup_db):
    async with TestSession() as session:
        tenant = Tenant(name="Acme Corp")
        session.add(tenant); await session.flush()
        user = User(tenant_id=tenant.id, email="recruiter@acme.com", password_hash=hash_password("pass"), full_name="Recruiter", role="recruiter")
        session.add(user); await session.flush()
        pos = Position(tenant_id=tenant.id, title="Software Engineer", created_by=user.id)
        session.add(pos); await session.flush()
        cand = Candidate(tenant_id=tenant.id, position_id=pos.id, name="Alice Martin", email="alice@example.com", phone="+212600000000", pipeline_status="cv_scored")
        session.add(cand); await session.flush()
        token = secrets.token_urlsafe(32)
        consent = Consent(candidate_id=cand.id, token=token, type="phone_interview", granted=False)
        session.add(consent); await session.flush()
        await session.commit()
        result = {
            "tenant_id": tenant.id,
            "user_id": user.id,
            "position_id": pos.id,
            "candidate_id": cand.id,
            "consent_id": consent.id,
            "token": token,
        }
    return result


# ─── GET /api/v1/consent/{token} ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_consent_status(client, seed):
    r = await client.get(f"/api/v1/consent/{seed['token']}")
    assert r.status_code == 200
    d = r.json()
    assert d["candidate_name"] == "Alice Martin"
    assert d["already_granted"] is False

@pytest.mark.asyncio
async def test_get_consent_already_granted(client, seed):
    # Update consent to granted via a separate session
    async with TestSession() as session:
        from sqlalchemy import select
        result = await session.execute(select(Consent).where(Consent.id == seed["consent_id"]))
        consent = result.scalar_one()
        consent.granted = True
        await session.commit()
    r = await client.get(f"/api/v1/consent/{seed['token']}")
    assert r.status_code == 200
    assert r.json()["already_granted"] is True

@pytest.mark.asyncio
async def test_get_consent_not_found(client, _setup_db):
    r = await client.get(f"/api/v1/consent/{secrets.token_urlsafe(32)}")
    assert r.status_code == 404


# ─── POST /api/v1/consent/{token} ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_grant_consent(client, seed):
    r = await client.post(f"/api/v1/consent/{seed['token']}", json={"granted": True})
    assert r.status_code == 200
    assert r.json()["granted"] is True
    assert r.json()["granted_at"] is not None

@pytest.mark.asyncio
async def test_grant_consent_updates_pipeline(client, seed):
    await client.post(f"/api/v1/consent/{seed['token']}", json={"granted": True})
    async with TestSession() as session:
        from sqlalchemy import select
        result = await session.execute(select(Candidate).where(Candidate.id == seed["candidate_id"]))
        cand = result.scalar_one()
        assert cand.pipeline_status == "consent_given"

@pytest.mark.asyncio
async def test_grant_false_no_pipeline_change(client, seed):
    await client.post(f"/api/v1/consent/{seed['token']}", json={"granted": False})
    async with TestSession() as session:
        from sqlalchemy import select
        result = await session.execute(select(Candidate).where(Candidate.id == seed["candidate_id"]))
        cand = result.scalar_one()
        assert cand.pipeline_status == "cv_scored"

@pytest.mark.asyncio
async def test_grant_not_found(client, _setup_db):
    r = await client.post(f"/api/v1/consent/{secrets.token_urlsafe(32)}", json={"granted": True})
    assert r.status_code == 404

@pytest.mark.asyncio
async def test_consent_idempotent(client, seed):
    # Pre-grant the consent
    async with TestSession() as session:
        from sqlalchemy import select
        result = await session.execute(select(Consent).where(Consent.id == seed["consent_id"]))
        consent = result.scalar_one()
        consent.granted = True
        await session.commit()
    r = await client.post(f"/api/v1/consent/{seed['token']}", json={"granted": True})
    assert r.status_code == 400

@pytest.mark.asyncio
async def test_grants_all_pending(client, seed):
    # Add extra consent
    async with TestSession() as session:
        extra = Consent(candidate_id=seed["candidate_id"], token=secrets.token_urlsafe(32), type="data_processing", granted=False)
        session.add(extra)
        await session.commit()
        extra_id = extra.id
    await client.post(f"/api/v1/consent/{seed['token']}", json={"granted": True})
    async with TestSession() as session:
        from sqlalchemy import select
        result = await session.execute(select(Consent).where(Consent.id == extra_id))
        extra = result.scalar_one()
        assert extra.granted is True

@pytest.mark.asyncio
async def test_pipeline_only_after_grant(client, seed):
    # Check initial status
    async with TestSession() as session:
        from sqlalchemy import select
        result = await session.execute(select(Candidate).where(Candidate.id == seed["candidate_id"]))
        cand = result.scalar_one()
        assert cand.pipeline_status != "consent_given"
    await client.post(f"/api/v1/consent/{seed['token']}", json={"granted": True})
    async with TestSession() as session:
        result = await session.execute(select(Candidate).where(Candidate.id == seed["candidate_id"]))
        cand = result.scalar_one()
        assert cand.pipeline_status == "consent_given"

@pytest.mark.asyncio
async def test_revoke_not_supported(client, seed):
    await client.post(f"/api/v1/consent/{seed['token']}", json={"granted": True})
    r = await client.post(f"/api/v1/consent/{seed['token']}", json={"granted": False})
    assert r.status_code == 400

@pytest.mark.asyncio
async def test_missing_body(client, seed):
    r = await client.post(f"/api/v1/consent/{seed['token']}")
    assert r.status_code == 422
