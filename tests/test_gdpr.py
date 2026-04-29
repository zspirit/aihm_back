"""Tests for GDPR endpoints and granular consent."""
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
        tenant = Tenant(name="GDPR Corp")
        session.add(tenant); await session.flush()
        user = User(tenant_id=tenant.id, email="recruiter@gdpr.com", password_hash=hash_password("pass"), full_name="Recruiter", role="recruiter")
        session.add(user); await session.flush()
        pos = Position(tenant_id=tenant.id, title="Data Engineer", created_by=user.id)
        session.add(pos); await session.flush()
        cand = Candidate(tenant_id=tenant.id, position_id=pos.id, name="Bob Smith", email="bob@example.com", phone="+33600000001", pipeline_status="cv_scored",
                         cv_parsed_data={"skills": ["Python", "SQL"], "name": "Bob Smith"})
        session.add(cand); await session.flush()
        token = secrets.token_urlsafe(32)
        consent = Consent(candidate_id=cand.id, token=token, type="data_processing", granted=True)
        session.add(consent); await session.flush()
        await session.commit()
        result = {
            "tenant_id": tenant.id,
            "user_id": user.id,
            "position_id": pos.id,
            "candidate_id": cand.id,
            "token": token,
        }
    return result


# ─── POST /candidates/me (data access) ──────────────────────────────────────

@pytest.mark.asyncio
async def test_gdpr_access_data(client, seed):
    r = await client.post(f"/api/v1/candidates/me?token={seed['token']}")
    assert r.status_code == 200
    d = r.json()
    assert d["candidate"]["name"] == "Bob Smith"
    assert d["candidate"]["email"] == "bob@example.com"
    assert "scores" in d

@pytest.mark.asyncio
async def test_gdpr_access_invalid_token(client, _setup_db):
    r = await client.post(f"/api/v1/candidates/me?token={secrets.token_urlsafe(32)}")
    assert r.status_code == 404


# ─── DELETE /candidates/me (erasure) ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_gdpr_erasure(client, seed):
    r = await client.delete(f"/api/v1/candidates/me?token={seed['token']}")
    assert r.status_code == 204

    # Verify candidate is anonymized
    async with TestSession() as session:
        from sqlalchemy import select
        result = await session.execute(select(Candidate).where(Candidate.id == seed["candidate_id"]))
        cand = result.scalar_one()
        assert cand.is_anonymized is True
        assert cand.email is None
        assert cand.phone is None
        assert cand.cv_file_path is None

    # Verify consents are revoked
    async with TestSession() as session:
        from sqlalchemy import select
        result = await session.execute(select(Consent).where(Consent.candidate_id == seed["candidate_id"]))
        consents = result.scalars().all()
        for c in consents:
            assert c.granted is False
            assert c.revoked_at is not None


# ─── GET /candidates/me/portabilite (export) ─────────────────────────────────

@pytest.mark.asyncio
async def test_gdpr_portability(client, seed):
    r = await client.get(f"/api/v1/candidates/me/portabilite?token={seed['token']}")
    assert r.status_code == 200
    d = r.json()
    assert d["candidate"]["name"] == "Bob Smith"
    assert "interviews" in d
    assert "scores" in d
    assert "feedback_json" in d

@pytest.mark.asyncio
async def test_gdpr_portability_invalid_token(client, _setup_db):
    r = await client.get(f"/api/v1/candidates/me/portabilite?token={secrets.token_urlsafe(32)}")
    assert r.status_code == 404


# ─── Granular Consent Tests ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invite_creates_4_consent_types(client, seed):
    """invite_candidate should create 4 consent records."""
    from tests.conftest import _create_user, TestSession
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "admin@gdpr.com", "admin", "GDPR Corp2")
        pos = Position(tenant_id=tenant.id, title="Dev", created_by=user.id)
        session.add(pos); await session.flush()
        cand = Candidate(tenant_id=tenant.id, position_id=pos.id, name="Carol", email="carol@ex.com", pipeline_status="new")
        session.add(cand); await session.flush()
        cand_id = cand.id
        await session.commit()

    r = await client.post(f"/api/v1/candidates/{cand_id}/invite", headers=headers, json={})
    assert r.status_code == 200

    async with TestSession() as session:
        from sqlalchemy import select
        result = await session.execute(select(Consent).where(Consent.candidate_id == cand_id))
        consents = result.scalars().all()
        types = {c.type for c in consents}
        assert types == {"data_processing", "scoring", "call_recording", "data_transfer_us"}
        # Each has a unique token
        tokens = [c.token for c in consents]
        assert len(tokens) == len(set(tokens))


@pytest.mark.asyncio
async def test_grant_consent_admin_grants_all_4_types(client, seed):
    """grant_consent_admin should grant all 4 consent types."""
    from tests.conftest import _create_user, TestSession
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "admin2@gdpr.com", "admin", "GDPR Corp3")
        pos = Position(tenant_id=tenant.id, title="Dev", created_by=user.id)
        session.add(pos); await session.flush()
        cand = Candidate(tenant_id=tenant.id, position_id=pos.id, name="Dave", email="dave@ex.com", pipeline_status="invited")
        session.add(cand); await session.flush()
        cand_id = cand.id
        await session.commit()

    r = await client.post(f"/api/v1/candidates/{cand_id}/grant-consent", headers=headers)
    assert r.status_code == 200

    async with TestSession() as session:
        from sqlalchemy import select
        result = await session.execute(select(Consent).where(Consent.candidate_id == cand_id, Consent.granted.is_(True)))
        consents = result.scalars().all()
        types = {c.type for c in consents}
        assert "data_processing" in types
        assert "scoring" in types
        assert "call_recording" in types
        assert "data_transfer_us" in types


@pytest.mark.asyncio
async def test_legacy_data_processing_backward_compat(client, seed):
    """Existing data_processing consent should still work."""
    r = await client.get(f"/api/v1/consent/{seed['token']}")
    assert r.status_code == 200
    d = r.json()
    assert d["candidate_name"] == "Bob Smith"
