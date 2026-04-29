"""Smoke tests — post-deploy check that critical endpoints are reachable."""
import pytest
import pytest_asyncio

from tests.conftest import _create_user, TestSession


@pytest_asyncio.fixture()
async def auth_headers(_setup_db):
    async with TestSession() as session:
        headers, _, _ = await _create_user(session, "admin@test.com", "admin")
    return headers


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] in {"ok", "degraded"}

@pytest.mark.asyncio
async def test_login(client, _setup_db):
    from app.core.security import hash_password
    from app.models.tenant import Tenant
    from app.models.user import User
    async with TestSession() as session:
        tenant = Tenant(name="Smoke Corp")
        session.add(tenant)
        await session.flush()
        user = User(tenant_id=tenant.id, email="smoke@test.com", password_hash=hash_password("smokepass"), full_name="Smoke", role="admin")
        session.add(user)
        await session.commit()
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
async def test_auth_guard(client, _setup_db):
    for path in ["/api/v1/positions", "/api/v1/candidates", "/api/v1/settings", "/api/v1/auth/users", "/api/v1/imports/recent", "/api/v1/matching/sessions"]:
        r = await client.get(path)
        assert r.status_code == 401, f"Expected 401 for {path}, got {r.status_code}"


@pytest.mark.asyncio
async def test_analytics_overview(client, auth_headers):
    r = await client.get("/api/v1/analytics/overview", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert "total_positions" in data
    assert "total_candidates" in data
    assert "success_rate" in data


@pytest.mark.asyncio
async def test_analytics_pipeline(client, auth_headers):
    r = await client.get("/api/v1/analytics/pipeline", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


@pytest.mark.asyncio
async def test_analytics_timeline(client, auth_headers):
    r = await client.get("/api/v1/analytics/timeline", headers=auth_headers)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_auth_me(client, auth_headers):
    r = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert "email" in data
    assert "role" in data


@pytest.mark.asyncio
async def test_auth_guard_write_endpoints(client, _setup_db):
    """POST/PUT/DELETE endpoints should also reject unauthenticated requests."""
    write_paths = [
        ("post", "/api/v1/positions"),
        ("post", "/api/v1/auth/change-password"),
        ("patch", "/api/v1/settings"),
        ("post", "/api/v1/matching/sessions"),
    ]
    for method, path in write_paths:
        r = await getattr(client, method)(path, json={})
        assert r.status_code in (401, 422), f"Expected 401/422 for {method.upper()} {path}, got {r.status_code}"
