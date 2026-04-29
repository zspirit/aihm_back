"""Extended tests for auth/users endpoints."""
import pytest
import pytest_asyncio

from app.core.security import create_access_token, hash_password
from app.models.user import User

from tests.conftest import _create_user, TestSession


async def _add_user(session, tenant_id, email, role="recruiter", full_name="Extra User"):
    user = User(tenant_id=tenant_id, email=email, password_hash=hash_password("testpass123"), full_name=full_name, role=role)
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture()
async def admin_data(_setup_db):
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "admin@test.com", "admin")
        user_id = user.id
        tenant_id = tenant.id
    return headers, user_id, tenant_id


@pytest_asyncio.fixture()
async def viewer_headers(_setup_db):
    async with TestSession() as session:
        headers, _, _ = await _create_user(session, "viewer@test.com", "viewer", "Viewer Corp")
    return headers


# ─── PUT /auth/users/{id} ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_user_name(client, admin_data):
    headers, _, tenant_id = admin_data
    async with TestSession() as session:
        target = await _add_user(session, tenant_id, "target@test.com")
        await session.commit()
        target_id = target.id
    resp = await client.put(f"/api/v1/auth/users/{target_id}", json={"full_name": "Updated"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Updated"

@pytest.mark.asyncio
async def test_update_user_role(client, admin_data):
    headers, _, tenant_id = admin_data
    async with TestSession() as session:
        target = await _add_user(session, tenant_id, "role@test.com", role="admin")
        await session.commit()
        target_id = target.id
    resp = await client.put(f"/api/v1/auth/users/{target_id}", json={"role": "recruiter"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["role"] == "recruiter"

@pytest.mark.asyncio
async def test_update_user_email(client, admin_data):
    headers, _, tenant_id = admin_data
    async with TestSession() as session:
        target = await _add_user(session, tenant_id, "old@test.com")
        await session.commit()
        target_id = target.id
    resp = await client.put(f"/api/v1/auth/users/{target_id}", json={"email": "new@test.com"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "new@test.com"

@pytest.mark.asyncio
async def test_update_user_not_found(client, admin_data):
    headers, _, _ = admin_data
    resp = await client.put("/api/v1/auth/users/00000000-0000-0000-0000-000000000001", json={"full_name": "Ghost"}, headers=headers)
    assert resp.status_code == 404


# ─── DELETE /auth/users/{id} ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_user(client, admin_data):
    headers, _, tenant_id = admin_data
    async with TestSession() as session:
        target = await _add_user(session, tenant_id, "delete_me@test.com")
        await session.commit()
        target_id = target.id
    resp = await client.delete(f"/api/v1/auth/users/{target_id}", headers=headers)
    assert resp.status_code == 204

@pytest.mark.asyncio
async def test_delete_self_forbidden(client, admin_data):
    headers, admin_user_id, _ = admin_data
    resp = await client.delete(f"/api/v1/auth/users/{admin_user_id}", headers=headers)
    assert resp.status_code == 400
    assert "propre compte" in resp.json()["detail"]

@pytest.mark.asyncio
async def test_delete_user_not_found(client, admin_data):
    headers, _, _ = admin_data
    resp = await client.delete("/api/v1/auth/users/00000000-0000-0000-0000-000000000002", headers=headers)
    assert resp.status_code == 404


# ─── POST /auth/users/bulk-delete ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_bulk_delete_users(client, admin_data):
    headers, _, tenant_id = admin_data
    async with TestSession() as session:
        u1 = await _add_user(session, tenant_id, "bulk1@test.com")
        u2 = await _add_user(session, tenant_id, "bulk2@test.com")
        await session.commit()
        u1_id = str(u1.id)
        u2_id = str(u2.id)
    resp = await client.post("/api/v1/auth/users/bulk-delete", json={"ids": [u1_id, u2_id]}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 2

@pytest.mark.asyncio
async def test_bulk_delete_excludes_self(client, admin_data):
    headers, admin_user_id, tenant_id = admin_data
    async with TestSession() as session:
        other = await _add_user(session, tenant_id, "bulk_other@test.com")
        await session.commit()
        other_id = str(other.id)
    resp = await client.post("/api/v1/auth/users/bulk-delete", json={"ids": [str(admin_user_id), other_id]}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1

@pytest.mark.asyncio
async def test_bulk_delete_empty(client, admin_data):
    headers, _, _ = admin_data
    resp = await client.post("/api/v1/auth/users/bulk-delete", json={"ids": []}, headers=headers)
    assert resp.status_code == 400


# ─── GET /auth/users ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_users(client, admin_data):
    headers, _, tenant_id = admin_data
    async with TestSession() as session:
        await _add_user(session, tenant_id, "list1@test.com")
        await _add_user(session, tenant_id, "list2@test.com")
        await session.commit()
    resp = await client.get("/api/v1/auth/users", headers=headers)
    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()}
    assert "admin@test.com" in emails
    assert "list1@test.com" in emails


# ─── POST /auth/users (invite) ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invite_user(client, admin_data):
    headers, _, _ = admin_data
    resp = await client.post("/api/v1/auth/users", json={"email": "newbie@test.com", "full_name": "New", "password": "securePass1", "role": "recruiter"}, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["email"] == "newbie@test.com"

@pytest.mark.asyncio
async def test_invite_duplicate_email(client, admin_data):
    headers, _, tenant_id = admin_data
    async with TestSession() as session:
        await _add_user(session, tenant_id, "dup@test.com")
        await session.commit()
    resp = await client.post("/api/v1/auth/users", json={"email": "dup@test.com", "full_name": "Dup", "password": "securePass1", "role": "viewer"}, headers=headers)
    assert resp.status_code == 400


# ─── Viewer guards ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_viewer_cannot_update_user(client, viewer_headers):
    resp = await client.put("/api/v1/auth/users/00000000-0000-0000-0000-000000000099", json={"full_name": "Hacker"}, headers=viewer_headers)
    assert resp.status_code == 403

@pytest.mark.asyncio
async def test_viewer_cannot_delete_user(client, viewer_headers):
    resp = await client.delete("/api/v1/auth/users/00000000-0000-0000-0000-000000000099", headers=viewer_headers)
    assert resp.status_code == 403


# ─── PUT /auth/me ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_profile(client, admin_data):
    headers, _, _ = admin_data
    # Use the auth_headers from admin_data (the fixture already closed its session)
    resp = await client.put("/api/v1/auth/me", json={"full_name": "New Name", "email": "updated@test.com"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "New Name"


# ─── POST /auth/change-password ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_change_password(client, admin_data):
    headers, _, _ = admin_data
    resp = await client.post("/api/v1/auth/change-password", json={"current_password": "testpass123", "new_password": "NewPass456!"}, headers=headers)
    assert resp.status_code == 200

@pytest.mark.asyncio
async def test_change_password_wrong(client, admin_data):
    headers, _, _ = admin_data
    resp = await client.post("/api/v1/auth/change-password", json={"current_password": "wrong", "new_password": "NewPass456!"}, headers=headers)
    assert resp.status_code == 400


# ─── Register edge cases ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_missing_fields(client, _setup_db):
    """Registration with missing required fields should fail."""
    resp = await client.post("/api/v1/auth/register", json={"email": "incomplete@test.com"})
    assert resp.status_code == 422

@pytest.mark.asyncio
async def test_register_duplicate_email(client, _setup_db):
    """Registering twice with the same email should fail."""
    payload = {"company_name": "Dup Corp", "email": "dup_reg@test.com", "password": "Pass1234!", "full_name": "Dup"}
    r1 = await client.post("/api/v1/auth/register", json=payload)
    assert r1.status_code == 201
    r2 = await client.post("/api/v1/auth/register", json=payload)
    assert r2.status_code == 400

@pytest.mark.asyncio
async def test_login_wrong_password(client, _setup_db):
    """Login with wrong password should return 401."""
    await client.post("/api/v1/auth/register", json={"company_name": "WP Corp", "email": "wp@test.com", "password": "GoodPass1!", "full_name": "WP"})
    resp = await client.post("/api/v1/auth/login", json={"email": "wp@test.com", "password": "WrongPass!"})
    assert resp.status_code == 401

@pytest.mark.asyncio
async def test_login_nonexistent_user(client, _setup_db):
    """Login with unknown email should return 401."""
    resp = await client.post("/api/v1/auth/login", json={"email": "ghost@test.com", "password": "Pass1234!"})
    assert resp.status_code == 401

@pytest.mark.asyncio
async def test_viewer_cannot_invite_user(client, viewer_headers):
    """Viewer role should not be able to create new users."""
    resp = await client.post("/api/v1/auth/users", json={"email": "hack@test.com", "full_name": "Hack", "password": "securePass1", "role": "recruiter"}, headers=viewer_headers)
    assert resp.status_code == 403
