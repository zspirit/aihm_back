"""Tests for webhook config CRUD endpoints (webhooks_config.py)."""

import uuid

import pytest
import pytest_asyncio

from tests.conftest import _create_user, TestSession


@pytest_asyncio.fixture()
async def auth_headers(_setup_db):
    async with TestSession() as session:
        headers, _, _ = await _create_user(session, "admin@test.com", "admin")
    return headers


@pytest_asyncio.fixture()
async def viewer_headers(_setup_db):
    async with TestSession() as session:
        headers, _, _ = await _create_user(session, "viewer@test.com", "viewer", "Viewer Corp")
    return headers


# --- List events ---

@pytest.mark.asyncio
async def test_list_events(client, auth_headers):
    resp = await client.get("/api/v1/webhooks/events", headers=auth_headers)
    assert resp.status_code == 200
    events = resp.json()
    assert "consent.given" in events
    assert "interview.completed" in events
    assert "report.ready" in events
    assert "cv.scored" in events


@pytest.mark.asyncio
async def test_list_events_unauthenticated(client, _setup_db):
    resp = await client.get("/api/v1/webhooks/events")
    assert resp.status_code in (401, 403)


# --- Create webhook ---

@pytest.mark.asyncio
async def test_create_webhook(client, auth_headers):
    resp = await client.post(
        "/api/v1/webhooks",
        json={"url": "https://example.com/hook", "events": ["consent.given"]},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["url"] == "https://example.com/hook"
    assert data["events"] == ["consent.given"]
    assert data["is_active"] is True
    assert len(data["secret"]) == 64  # token_hex(32) = 64 chars


@pytest.mark.asyncio
async def test_create_webhook_invalid_event(client, auth_headers):
    resp = await client.post(
        "/api/v1/webhooks",
        json={"url": "https://example.com/hook", "events": ["invalid.event"]},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "invalides" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_create_webhook_invalid_url(client, auth_headers):
    resp = await client.post(
        "/api/v1/webhooks",
        json={"url": "not-a-url", "events": ["consent.given"]},
        headers=auth_headers,
    )
    assert resp.status_code == 422  # Pydantic validation


@pytest.mark.asyncio
async def test_create_webhook_multiple_events(client, auth_headers):
    resp = await client.post(
        "/api/v1/webhooks",
        json={
            "url": "https://example.com/multi",
            "events": ["consent.given", "report.ready"],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert set(resp.json()["events"]) == {"consent.given", "report.ready"}


# --- List webhooks ---

@pytest.mark.asyncio
async def test_list_webhooks_empty(client, auth_headers):
    resp = await client.get("/api/v1/webhooks", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_webhooks_with_data(client, auth_headers):
    # Create one
    await client.post(
        "/api/v1/webhooks",
        json={"url": "https://example.com/hook", "events": ["consent.given"]},
        headers=auth_headers,
    )
    resp = await client.get("/api/v1/webhooks", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["url"] == "https://example.com/hook"
    # Secret is truncated in list
    assert data[0]["secret"].endswith("...")


@pytest.mark.asyncio
async def test_list_webhooks_unauthenticated(client, _setup_db):
    resp = await client.get("/api/v1/webhooks")
    assert resp.status_code in (401, 403)


# --- Delete webhook ---

@pytest.mark.asyncio
async def test_delete_webhook(client, auth_headers):
    create_resp = await client.post(
        "/api/v1/webhooks",
        json={"url": "https://example.com/del", "events": ["cv.scored"]},
        headers=auth_headers,
    )
    wh_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/api/v1/webhooks/{wh_id}", headers=auth_headers)
    assert del_resp.status_code == 204

    # Confirm gone
    list_resp = await client.get("/api/v1/webhooks", headers=auth_headers)
    assert len(list_resp.json()) == 0


@pytest.mark.asyncio
async def test_delete_webhook_not_found(client, auth_headers):
    fake_id = str(uuid.uuid4())
    resp = await client.delete(f"/api/v1/webhooks/{fake_id}", headers=auth_headers)
    assert resp.status_code == 404


# --- Toggle webhook ---

@pytest.mark.asyncio
async def test_toggle_webhook(client, auth_headers):
    create_resp = await client.post(
        "/api/v1/webhooks",
        json={"url": "https://example.com/toggle", "events": ["report.ready"]},
        headers=auth_headers,
    )
    wh_id = create_resp.json()["id"]
    assert create_resp.json()["is_active"] is True

    # Toggle off
    toggle_resp = await client.patch(f"/api/v1/webhooks/{wh_id}/toggle", headers=auth_headers)
    assert toggle_resp.status_code == 200
    assert toggle_resp.json()["is_active"] is False

    # Toggle back on
    toggle_resp2 = await client.patch(f"/api/v1/webhooks/{wh_id}/toggle", headers=auth_headers)
    assert toggle_resp2.json()["is_active"] is True


@pytest.mark.asyncio
async def test_toggle_webhook_not_found(client, auth_headers):
    fake_id = str(uuid.uuid4())
    resp = await client.patch(f"/api/v1/webhooks/{fake_id}/toggle", headers=auth_headers)
    assert resp.status_code == 404


# --- Multi-tenant isolation ---

@pytest.mark.asyncio
async def test_tenant_isolation_list(client, auth_headers, _setup_db):
    """Webhook created by tenant A is not visible to tenant B."""
    await client.post(
        "/api/v1/webhooks",
        json={"url": "https://a.com/hook", "events": ["consent.given"]},
        headers=auth_headers,
    )

    async with TestSession() as session:
        other_headers, _, _ = await _create_user(session, "other@corp.com", "admin", "Other Corp")
    resp = await client.get("/api/v1/webhooks", headers=other_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 0


@pytest.mark.asyncio
async def test_tenant_isolation_delete(client, auth_headers, _setup_db):
    """Tenant B cannot delete tenant A's webhook."""
    create_resp = await client.post(
        "/api/v1/webhooks",
        json={"url": "https://a.com/hook", "events": ["consent.given"]},
        headers=auth_headers,
    )
    wh_id = create_resp.json()["id"]

    async with TestSession() as session:
        other_headers, _, _ = await _create_user(session, "other2@corp.com", "admin", "Other Corp 2")
    resp = await client.delete(f"/api/v1/webhooks/{wh_id}", headers=other_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_tenant_isolation_toggle(client, auth_headers, _setup_db):
    """Tenant B cannot toggle tenant A's webhook."""
    create_resp = await client.post(
        "/api/v1/webhooks",
        json={"url": "https://a.com/hook", "events": ["consent.given"]},
        headers=auth_headers,
    )
    wh_id = create_resp.json()["id"]

    async with TestSession() as session:
        other_headers, _, _ = await _create_user(session, "other3@corp.com", "admin", "Other Corp 3")
    resp = await client.patch(f"/api/v1/webhooks/{wh_id}/toggle", headers=other_headers)
    assert resp.status_code == 404


# --- Role-based access (viewer cannot manage webhooks) ---

@pytest.mark.asyncio
async def test_viewer_cannot_create_webhook(client, viewer_headers):
    resp = await client.post(
        "/api/v1/webhooks",
        json={"url": "https://example.com/hook", "events": ["consent.given"]},
        headers=viewer_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_viewer_cannot_list_webhooks(client, viewer_headers):
    resp = await client.get("/api/v1/webhooks", headers=viewer_headers)
    assert resp.status_code == 403
