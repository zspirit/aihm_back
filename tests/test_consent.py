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


@pytest_asyncio.fixture()
async def seed(db_session):
    tenant = Tenant(name="Acme Corp")
    db_session.add(tenant); await db_session.commit(); await db_session.refresh(tenant)
    user = User(tenant_id=tenant.id, email="recruiter@acme.com", password_hash=hash_password("pass"), full_name="Recruiter", role="recruiter")
    db_session.add(user); await db_session.commit(); await db_session.refresh(user)
    pos = Position(tenant_id=tenant.id, title="Software Engineer", created_by=user.id)
    db_session.add(pos); await db_session.commit(); await db_session.refresh(pos)
    cand = Candidate(tenant_id=tenant.id, position_id=pos.id, name="Alice Martin", email="alice@example.com", phone="+212600000000", pipeline_status="cv_scored")
    db_session.add(cand); await db_session.commit(); await db_session.refresh(cand)
    token = secrets.token_urlsafe(32)
    consent = Consent(candidate_id=cand.id, token=token, type="phone_interview", granted=False)
    db_session.add(consent); await db_session.commit(); await db_session.refresh(consent)
    return {"tenant": tenant, "user": user, "position": pos, "candidate": cand, "consent": consent, "token": token}


# ─── GET /api/v1/consent/{token} ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_consent_status(client, seed):
    r = await client.get(f"/api/v1/consent/{seed['token']}")
    assert r.status_code == 200
    d = r.json()
    assert d["candidate_name"] == "Alice Martin"
    assert d["already_granted"] is False

@pytest.mark.asyncio
async def test_get_consent_already_granted(client, db_session, seed):
    seed["consent"].granted = True
    await db_session.commit()
    r = await client.get(f"/api/v1/consent/{seed['token']}")
    assert r.status_code == 200
    assert r.json()["already_granted"] is True

@pytest.mark.asyncio
async def test_get_consent_not_found(client):
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
async def test_grant_consent_updates_pipeline(client, db_session, seed):
    await client.post(f"/api/v1/consent/{seed['token']}", json={"granted": True})
    await db_session.refresh(seed["candidate"])
    assert seed["candidate"].pipeline_status == "consent_given"

@pytest.mark.asyncio
async def test_grant_false_no_pipeline_change(client, db_session, seed):
    original = seed["candidate"].pipeline_status
    await client.post(f"/api/v1/consent/{seed['token']}", json={"granted": False})
    await db_session.refresh(seed["candidate"])
    assert seed["candidate"].pipeline_status == original

@pytest.mark.asyncio
async def test_grant_not_found(client):
    r = await client.post(f"/api/v1/consent/{secrets.token_urlsafe(32)}", json={"granted": True})
    assert r.status_code == 404

@pytest.mark.asyncio
async def test_consent_idempotent(client, db_session, seed):
    seed["consent"].granted = True
    await db_session.commit()
    r = await client.post(f"/api/v1/consent/{seed['token']}", json={"granted": True})
    assert r.status_code == 400

@pytest.mark.asyncio
async def test_grants_all_pending(client, db_session, seed):
    extra = Consent(candidate_id=seed["candidate"].id, token=secrets.token_urlsafe(32), type="data_processing", granted=False)
    db_session.add(extra); await db_session.commit()
    await client.post(f"/api/v1/consent/{seed['token']}", json={"granted": True})
    await db_session.refresh(extra)
    assert extra.granted is True

@pytest.mark.asyncio
async def test_pipeline_only_after_grant(client, db_session, seed):
    assert seed["candidate"].pipeline_status != "consent_given"
    await client.post(f"/api/v1/consent/{seed['token']}", json={"granted": True})
    await db_session.refresh(seed["candidate"])
    assert seed["candidate"].pipeline_status == "consent_given"

@pytest.mark.asyncio
async def test_revoke_not_supported(client, seed):
    await client.post(f"/api/v1/consent/{seed['token']}", json={"granted": True})
    r = await client.post(f"/api/v1/consent/{seed['token']}", json={"granted": False})
    assert r.status_code == 400

@pytest.mark.asyncio
async def test_missing_body(client, seed):
    r = await client.post(f"/api/v1/consent/{seed['token']}")
    assert r.status_code == 422
