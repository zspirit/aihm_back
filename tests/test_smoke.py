"""Smoke tests — post-deploy check that critical endpoints are reachable."""
import pytest


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] in {"ok", "degraded"}

@pytest.mark.asyncio
async def test_login(client, db_session):
    from app.core.security import hash_password
    from app.models.tenant import Tenant
    from app.models.user import User
    tenant = Tenant(name="Smoke Corp"); db_session.add(tenant); await db_session.commit(); await db_session.refresh(tenant)
    user = User(tenant_id=tenant.id, email="smoke@test.com", password_hash=hash_password("smokepass"), full_name="Smoke", role="admin")
    db_session.add(user); await db_session.commit()
    r = await client.post("/api/v1/auth/login", json={"email": "smoke@test.com", "password": "smokepass"})
    assert r.status_code == 200
    assert "access_token" in r.json()

@pytest.mark.asyncio
async def test_list_positions(client, auth_headers):
    r = await client.get("/api/v1/positions", headers=auth_headers)
    assert r.status_code == 200
    assert "items" in r.json()

@pytest.mark.asyncio
async def test_list_candidates(client, auth_headers):
    r = await client.get("/api/v1/candidates", headers=auth_headers)
    assert r.status_code == 200
    assert "items" in r.json()

@pytest.mark.asyncio
async def test_settings(client, auth_headers):
    r = await client.get("/api/v1/settings", headers=auth_headers)
    assert r.status_code == 200
    assert "name" in r.json()

@pytest.mark.asyncio
async def test_list_users(client, auth_headers):
    r = await client.get("/api/v1/auth/users", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)

@pytest.mark.asyncio
async def test_recent_imports(client, auth_headers):
    r = await client.get("/api/v1/imports/recent", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)

@pytest.mark.asyncio
async def test_matching_sessions(client, auth_headers):
    r = await client.get("/api/v1/matching/sessions", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)

@pytest.mark.asyncio
async def test_auth_guard(client):
    for path in ["/api/v1/positions", "/api/v1/candidates", "/api/v1/settings", "/api/v1/auth/users", "/api/v1/imports/recent", "/api/v1/matching/sessions"]:
        r = await client.get(path)
        assert r.status_code == 401, f"Expected 401 for {path}, got {r.status_code}"
