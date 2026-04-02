"""Extended tests for auth/users endpoints."""
import pytest
from app.core.security import create_access_token, hash_password
from app.models.user import User


async def _add_user(db_session, tenant_id, email, role="recruiter", full_name="Extra User"):
    user = User(tenant_id=tenant_id, email=email, password_hash=hash_password("testpass123"), full_name=full_name, role=role)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ─── PUT /auth/users/{id} ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_user_name(client, admin_data, db_session):
    headers, _, tenant = admin_data
    target = await _add_user(db_session, tenant.id, "target@test.com")
    resp = await client.put(f"/api/v1/auth/users/{target.id}", json={"full_name": "Updated"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Updated"

@pytest.mark.asyncio
async def test_update_user_role(client, admin_data, db_session):
    headers, _, tenant = admin_data
    target = await _add_user(db_session, tenant.id, "role@test.com", role="admin")
    resp = await client.put(f"/api/v1/auth/users/{target.id}", json={"role": "recruiter"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["role"] == "recruiter"

@pytest.mark.asyncio
async def test_update_user_email(client, admin_data, db_session):
    headers, _, tenant = admin_data
    target = await _add_user(db_session, tenant.id, "old@test.com")
    resp = await client.put(f"/api/v1/auth/users/{target.id}", json={"email": "new@test.com"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "new@test.com"

@pytest.mark.asyncio
async def test_update_user_not_found(client, admin_data):
    headers, _, _ = admin_data
    resp = await client.put("/api/v1/auth/users/00000000-0000-0000-0000-000000000001", json={"full_name": "Ghost"}, headers=headers)
    assert resp.status_code == 404


# ─── DELETE /auth/users/{id} ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_user(client, admin_data, db_session):
    headers, _, tenant = admin_data
    target = await _add_user(db_session, tenant.id, "delete_me@test.com")
    resp = await client.delete(f"/api/v1/auth/users/{target.id}", headers=headers)
    assert resp.status_code == 204

@pytest.mark.asyncio
async def test_delete_self_forbidden(client, admin_data):
    headers, admin_user, _ = admin_data
    resp = await client.delete(f"/api/v1/auth/users/{admin_user.id}", headers=headers)
    assert resp.status_code == 400
    assert "propre compte" in resp.json()["detail"]

@pytest.mark.asyncio
async def test_delete_user_not_found(client, admin_data):
    headers, _, _ = admin_data
    resp = await client.delete("/api/v1/auth/users/00000000-0000-0000-0000-000000000002", headers=headers)
    assert resp.status_code == 404


# ─── POST /auth/users/bulk-delete ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_bulk_delete_users(client, admin_data, db_session):
    headers, _, tenant = admin_data
    u1 = await _add_user(db_session, tenant.id, "bulk1@test.com")
    u2 = await _add_user(db_session, tenant.id, "bulk2@test.com")
    resp = await client.post("/api/v1/auth/users/bulk-delete", json={"ids": [str(u1.id), str(u2.id)]}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 2

@pytest.mark.asyncio
async def test_bulk_delete_excludes_self(client, admin_data, db_session):
    headers, admin_user, tenant = admin_data
    other = await _add_user(db_session, tenant.id, "bulk_other@test.com")
    resp = await client.post("/api/v1/auth/users/bulk-delete", json={"ids": [str(admin_user.id), str(other.id)]}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 1

@pytest.mark.asyncio
async def test_bulk_delete_empty(client, admin_data):
    headers, _, _ = admin_data
    resp = await client.post("/api/v1/auth/users/bulk-delete", json={"ids": []}, headers=headers)
    assert resp.status_code == 400


# ─── GET /auth/users ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_users(client, admin_data, db_session):
    headers, _, tenant = admin_data
    await _add_user(db_session, tenant.id, "list1@test.com")
    await _add_user(db_session, tenant.id, "list2@test.com")
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
async def test_invite_duplicate_email(client, admin_data, db_session):
    headers, _, tenant = admin_data
    await _add_user(db_session, tenant.id, "dup@test.com")
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
async def test_update_profile(client, auth_headers):
    resp = await client.put("/api/v1/auth/me", json={"full_name": "New Name", "email": "updated@test.com"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "New Name"


# ─── POST /auth/change-password ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_change_password(client, auth_headers):
    resp = await client.post("/api/v1/auth/change-password", json={"current_password": "testpass123", "new_password": "NewPass456!"}, headers=auth_headers)
    assert resp.status_code == 200

@pytest.mark.asyncio
async def test_change_password_wrong(client, auth_headers):
    resp = await client.post("/api/v1/auth/change-password", json={"current_password": "wrong", "new_password": "NewPass456!"}, headers=auth_headers)
    assert resp.status_code == 400
