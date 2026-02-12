import pytest


@pytest.mark.asyncio
async def test_audit_logs_empty(client, admin_data):
    headers, *_ = admin_data
    res = await client.get("/api/v1/auth/audit-logs", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_audit_logs_after_login(client):
    """Register + login should produce audit entries."""
    # Register
    await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "AuditCo",
            "email": "audit@test.com",
            "password": "Test1234!",
            "full_name": "Audit User",
        },
    )
    # Login
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": "audit@test.com", "password": "Test1234!"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = await client.get("/api/v1/auth/audit-logs", headers=headers)
    assert res.status_code == 200
    data = res.json()
    actions = [e["action"] for e in data]
    assert "register" in actions
    assert "login" in actions


@pytest.mark.asyncio
async def test_audit_logs_pagination(client, admin_data):
    headers, *_ = admin_data
    res = await client.get(
        "/api/v1/auth/audit-logs", headers=headers, params={"limit": 5, "offset": 0}
    )
    assert res.status_code == 200
    assert isinstance(res.json(), list)
    assert len(res.json()) <= 5


@pytest.mark.asyncio
async def test_audit_logs_viewer_forbidden(client, viewer_headers):
    res = await client.get("/api/v1/auth/audit-logs", headers=viewer_headers)
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_audit_logs_no_auth(client):
    res = await client.get("/api/v1/auth/audit-logs")
    assert res.status_code == 401
