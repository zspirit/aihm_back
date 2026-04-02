"""Tests for positions bulk operations: bulk-delete, duplicate, import-text, optimize."""
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from tests.conftest import _create_user


async def _create_position(client, headers, title="Test Position"):
    r = await client.post("/api/v1/positions", json={"title": title, "description": "Test.", "required_skills": ["Python"], "seniority_level": "mid"}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest_asyncio.fixture()
async def admin_headers(db_session):
    headers, _, _ = await _create_user(db_session, "bulk_admin@test.com", "admin")
    return headers

@pytest_asyncio.fixture()
async def viewer_hdrs(db_session):
    headers, _, _ = await _create_user(db_session, "bulk_viewer@test.com", "viewer", "Viewer Bulk Corp")
    return headers


# ─── Bulk delete ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bulk_delete_positions(client, admin_headers):
    id1 = await _create_position(client, admin_headers, "A")
    id2 = await _create_position(client, admin_headers, "B")
    r = await client.post("/api/v1/positions/bulk-delete", json={"ids": [id1, id2]}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["deleted"] == 2

@pytest.mark.asyncio
async def test_bulk_delete_empty(client, admin_headers):
    r = await client.post("/api/v1/positions/bulk-delete", json={"ids": []}, headers=admin_headers)
    assert r.status_code == 400

@pytest.mark.asyncio
async def test_bulk_delete_max_limit(client, admin_headers):
    r = await client.post("/api/v1/positions/bulk-delete", json={"ids": [str(uuid4()) for _ in range(51)]}, headers=admin_headers)
    assert r.status_code == 400
    assert "50" in r.json()["detail"]

@pytest.mark.asyncio
async def test_bulk_delete_nonexistent(client, admin_headers):
    r = await client.post("/api/v1/positions/bulk-delete", json={"ids": [str(uuid4()), str(uuid4())]}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["deleted"] == 0


# ─── Duplicate ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_position(client, admin_headers):
    oid = await _create_position(client, admin_headers, "Senior Dev")
    r = await client.post(f"/api/v1/positions/{oid}/duplicate", headers=admin_headers)
    assert r.status_code == 201
    assert "Copie de" in r.json()["title"]
    assert r.json()["status"] == "draft"

@pytest.mark.asyncio
async def test_duplicate_custom_title(client, admin_headers):
    oid = await _create_position(client, admin_headers, "Backend")
    r = await client.post(f"/api/v1/positions/{oid}/duplicate", json={"title": "Backend Paris"}, headers=admin_headers)
    assert r.status_code == 201
    assert r.json()["title"] == "Backend Paris"

@pytest.mark.asyncio
async def test_duplicate_not_found(client, admin_headers):
    r = await client.post(f"/api/v1/positions/{uuid4()}/duplicate", headers=admin_headers)
    assert r.status_code == 404


# ─── Import text ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_import_text(client, admin_headers):
    mock_result = {"title": "Dev Python", "description": "Backend.", "required_skills": ["Python"], "seniority_level": "senior", "custom_questions": []}
    # patch where the name is looked up (the router module), not where it's defined
    with patch("app.api.v1.positions.extract_position_from_text", return_value=mock_result):
        r = await client.post("/api/v1/positions/import-text", json={"text": "Dev Python senior 7 ans"}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["title"] == "Dev Python"


# ─── Optimize ───────────────────────────────────────────────────────────────

_OPT_JSON = json.dumps({"clarity_score": 8, "clarity_suggestions": ["Preciser"], "missing_skills": [], "inclusivity_score": 9, "inclusivity_flags": [], "competitiveness_score": 7, "competitiveness_suggestions": [], "suggested_questions": [], "improved_description": "Amelioree."})

def _claude_resp(text):
    c = MagicMock(); c.text = text
    r = MagicMock(); r.content = [c]
    return r

@pytest.mark.asyncio
async def test_optimize_position(client, admin_headers):
    pid = await _create_position(client, admin_headers, "DevOps")
    with patch("asyncio.to_thread", new_callable=AsyncMock) as mt:
        mt.return_value = _claude_resp(_OPT_JSON)
        r = await client.post(f"/api/v1/positions/{pid}/optimize", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["clarity_score"] == 8

@pytest.mark.asyncio
async def test_optimize_not_found(client, admin_headers):
    with patch("asyncio.to_thread", new_callable=AsyncMock) as mt:
        mt.return_value = _claude_resp(_OPT_JSON)
        r = await client.post(f"/api/v1/positions/{uuid4()}/optimize", headers=admin_headers)
    assert r.status_code == 404


# ─── RBAC ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_viewer_cannot_bulk_delete(client, viewer_hdrs):
    r = await client.post("/api/v1/positions/bulk-delete", json={"ids": [str(uuid4())]}, headers=viewer_hdrs)
    assert r.status_code == 403

@pytest.mark.asyncio
async def test_viewer_cannot_duplicate(client, viewer_hdrs):
    r = await client.post(f"/api/v1/positions/{uuid4()}/duplicate", headers=viewer_hdrs)
    assert r.status_code == 403
