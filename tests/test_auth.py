import pytest


@pytest.mark.asyncio
async def test_register(client):
    res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "new@example.com",
            "password": "securepass123",
            "full_name": "New User",
            "company_name": "New Corp",
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    payload = {
        "email": "dup@example.com",
        "password": "securepass123",
        "full_name": "Dup User",
        "company_name": "Dup Corp",
    }
    res1 = await client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 201

    res2 = await client.post("/api/v1/auth/register", json=payload)
    assert res2.status_code == 400
    assert "deja utilise" in res2.json()["detail"]


@pytest.mark.asyncio
async def test_login(client):
    # Register first
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "login@example.com",
            "password": "mypassword",
            "full_name": "Login User",
            "company_name": "Login Corp",
        },
    )

    # Login
    res = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "login@example.com",
            "password": "mypassword",
        },
    )
    assert res.status_code == 200
    assert "access_token" in res.json()


@pytest.mark.asyncio
async def test_login_bad_password(client):
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "bad@example.com",
            "password": "correct",
            "full_name": "Bad Pass",
            "company_name": "Corp",
        },
    )

    res = await client.post(
        "/api/v1/auth/login",
        json={
            "email": "bad@example.com",
            "password": "wrong",
        },
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_me(client, auth_headers):
    res = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "admin@test.com"
    assert data["role"] == "admin"


@pytest.mark.asyncio
async def test_me_no_auth(client):
    res = await client.get("/api/v1/auth/me")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_invite_user(client, auth_headers):
    res = await client.post(
        "/api/v1/auth/users",
        headers=auth_headers,
        json={
            "email": "invited@test.com",
            "password": "invitedpass",
            "full_name": "Invited User",
            "role": "recruiter",
        },
    )
    assert res.status_code == 201
    assert res.json()["role"] == "recruiter"


@pytest.mark.asyncio
async def test_invite_user_viewer_forbidden(client, viewer_headers):
    res = await client.post(
        "/api/v1/auth/users",
        headers=viewer_headers,
        json={
            "email": "nope@test.com",
            "password": "nopepass",
            "full_name": "Nope User",
            "role": "viewer",
        },
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_list_users(client, auth_headers):
    res = await client.get("/api/v1/auth/users", headers=auth_headers)
    assert res.status_code == 200
    assert isinstance(res.json(), list)
    assert len(res.json()) >= 1


@pytest.mark.asyncio
async def test_refresh_token(client):
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "refresh@example.com",
            "password": "refreshpass",
            "full_name": "Refresh User",
            "company_name": "Refresh Corp",
        },
    )
    refresh_token = reg_res.json()["refresh_token"]

    res = await client.post(
        "/api/v1/auth/refresh",
        json={
            "refresh_token": refresh_token,
        },
    )
    assert res.status_code == 200
    assert "access_token" in res.json()
