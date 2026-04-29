"""Tests for /api/v1/candidates/{candidate_id}/applications endpoints."""
import pytest
import pytest_asyncio
from tests.conftest import _create_user, TestSession


@pytest_asyncio.fixture()
async def ctx(_setup_db, client):
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "app_admin@test.com", "admin", "AppCorp")
    pos = await client.post("/api/v1/positions", headers=headers, json={"title": "Backend", "required_skills": ["Python"]})
    pos_id = pos.json()["id"]
    cand = await client.post(f"/api/v1/positions/{pos_id}/candidates", headers=headers, data={"name": "Candidat", "email": "c@t.com"})
    cand_id = cand.json()["id"]
    pos2 = await client.post("/api/v1/positions", headers=headers, json={"title": "Frontend", "required_skills": ["React"]})
    pos2_id = pos2.json()["id"]
    return headers, cand_id, pos_id, pos2_id


# ─── Create ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_application(client, ctx):
    h, cid, _, pid2 = ctx
    r = await client.post(f"/api/v1/candidates/{cid}/applications", headers=h, json={"position_id": pid2})
    assert r.status_code == 201
    assert r.json()["candidate_id"] == cid
    assert r.json()["position_id"] == pid2

@pytest.mark.asyncio
async def test_create_duplicate(client, ctx):
    h, cid, _, pid2 = ctx
    await client.post(f"/api/v1/candidates/{cid}/applications", headers=h, json={"position_id": pid2})
    r = await client.post(f"/api/v1/candidates/{cid}/applications", headers=h, json={"position_id": pid2})
    assert r.status_code == 409


# ─── List ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_applications(client, ctx):
    h, cid, _, pid2 = ctx
    await client.post(f"/api/v1/candidates/{cid}/applications", headers=h, json={"position_id": pid2})
    r = await client.get(f"/api/v1/candidates/{cid}/applications", headers=h)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert any(a["position_id"] == pid2 for a in r.json())

@pytest.mark.asyncio
async def test_list_empty(client, _setup_db):
    async with TestSession() as session:
        headers, _, _ = await _create_user(session, "empty@t.com", "admin", "Empty")
    pos = await client.post("/api/v1/positions", headers=headers, json={"title": "E", "required_skills": []})
    cand = await client.post(f"/api/v1/positions/{pos.json()['id']}/candidates", headers=headers, data={"name": "Lonely"})
    r = await client.get(f"/api/v1/candidates/{cand.json()['id']}/applications", headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ─── Update decision ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_decision_accepted(client, ctx):
    h, cid, _, pid2 = ctx
    cr = await client.post(f"/api/v1/candidates/{cid}/applications", headers=h, json={"position_id": pid2})
    aid = cr.json()["id"]
    r = await client.put(f"/api/v1/candidates/{cid}/applications/{aid}/decision", headers=h, json={"decision": "accepted", "note": "Great fit"})
    assert r.status_code == 200
    assert r.json()["decision"] == "accepted"

@pytest.mark.asyncio
async def test_update_decision_rejected(client, ctx):
    h, cid, _, pid2 = ctx
    cr = await client.post(f"/api/v1/candidates/{cid}/applications", headers=h, json={"position_id": pid2})
    r = await client.put(f"/api/v1/candidates/{cid}/applications/{cr.json()['id']}/decision", headers=h, json={"decision": "rejected"})
    assert r.status_code == 200
    assert r.json()["decision"] == "rejected"


# ─── Delete ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_application(client, ctx):
    h, cid, _, pid2 = ctx
    cr = await client.post(f"/api/v1/candidates/{cid}/applications", headers=h, json={"position_id": pid2})
    aid = cr.json()["id"]
    r = await client.delete(f"/api/v1/candidates/{cid}/applications/{aid}", headers=h)
    assert r.status_code == 204

@pytest.mark.asyncio
async def test_delete_not_found(client, ctx):
    h, cid, _, _ = ctx
    r = await client.delete(f"/api/v1/candidates/{cid}/applications/00000000-0000-0000-0000-000000000099", headers=h)
    assert r.status_code == 404


# ─── RBAC ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_viewer_cannot_create(client, ctx, _setup_db):
    _, cid, _, pid2 = ctx
    async with TestSession() as session:
        vh, _, _ = await _create_user(session, "viewer_app@t.com", "viewer", "ViewerCorp")
    r = await client.post(f"/api/v1/candidates/{cid}/applications", headers=vh, json={"position_id": pid2})
    assert r.status_code in (403, 404)


# ─── Cross-tenant isolation ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cross_tenant_isolation(client, ctx, _setup_db):
    h, cid, _, pid2 = ctx
    cr = await client.post(f"/api/v1/candidates/{cid}/applications", headers=h, json={"position_id": pid2})
    aid = cr.json()["id"]
    async with TestSession() as session:
        other_h, _, _ = await _create_user(session, "other@t.com", "admin", "OtherCorp")
    assert (await client.get(f"/api/v1/candidates/{cid}/applications", headers=other_h)).status_code == 404
    assert (await client.post(f"/api/v1/candidates/{cid}/applications", headers=other_h, json={"position_id": pid2})).status_code == 404
    assert (await client.delete(f"/api/v1/candidates/{cid}/applications/{aid}", headers=other_h)).status_code == 404
