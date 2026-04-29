import uuid

import pytest
import pytest_asyncio

from app.models.notification import Notification
from tests.conftest import _create_user, TestSession


@pytest_asyncio.fixture()
async def notif_data(_setup_db):
    """Create user with 3 notifications (2 unread, 1 read).
    Uses its own session (closed before yield) to avoid deadlocks with ASGI client.
    """
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "notif@test.com", "admin")

        n1 = Notification(
            tenant_id=tenant.id,
            user_id=user.id,
            type="interview_completed",
            title="Interview terminee",
            message="L'interview de Alice est terminee.",
            data={"candidate_id": str(uuid.uuid4())},
            read=False,
        )
        n2 = Notification(
            tenant_id=tenant.id,
            user_id=user.id,
            type="report_ready",
            title="Rapport pret",
            message="Le rapport de Bob est disponible.",
            read=False,
        )
        n3 = Notification(
            tenant_id=tenant.id,
            user_id=user.id,
            type="cv_scored",
            title="CV evalue",
            message="Le CV de Charlie a ete evalue.",
            read=True,
        )
        session.add_all([n1, n2, n3])
        await session.commit()

        # Capture IDs before session closes
        notif_ids = [n1.id, n2.id, n3.id]

    return {
        "headers": headers,
        "user_id": user.id,
        "tenant_id": tenant.id,
        "notification_ids": notif_ids,
    }


@pytest.mark.asyncio
async def test_list_notifications_empty(client, auth_headers):
    resp = await client.get("/api/v1/notifications", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["unread_count"] == 0
    assert data["page"] == 1


@pytest.mark.asyncio
async def test_list_notifications_with_data(client, notif_data):
    resp = await client.get("/api/v1/notifications", headers=notif_data["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert data["unread_count"] == 2
    assert len(data["items"]) == 3


@pytest.mark.asyncio
async def test_list_notifications_filter_unread(client, notif_data):
    resp = await client.get("/api/v1/notifications?read=false", headers=notif_data["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert data["unread_count"] == 2
    for item in data["items"]:
        assert item["read"] is False


@pytest.mark.asyncio
async def test_list_notifications_filter_read(client, notif_data):
    resp = await client.get("/api/v1/notifications?read=true", headers=notif_data["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["read"] is True


@pytest.mark.asyncio
async def test_list_notifications_pagination(client, notif_data):
    resp = await client.get("/api/v1/notifications?page=1&page_size=2", headers=notif_data["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["total"] == 3
    assert data["page"] == 1

    resp2 = await client.get("/api/v1/notifications?page=2&page_size=2", headers=notif_data["headers"])
    data2 = resp2.json()
    assert len(data2["items"]) == 1


@pytest.mark.asyncio
async def test_mark_notification_read(client, notif_data):
    nid = str(notif_data["notification_ids"][0])
    resp = await client.patch(f"/api/v1/notifications/{nid}/read", headers=notif_data["headers"])
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Verify unread count decreased
    resp2 = await client.get("/api/v1/notifications", headers=notif_data["headers"])
    assert resp2.json()["unread_count"] == 1


@pytest.mark.asyncio
async def test_mark_notification_read_not_found(client, auth_headers):
    fake_id = str(uuid.uuid4())
    resp = await client.patch(f"/api/v1/notifications/{fake_id}/read", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Notification introuvable"


@pytest.mark.asyncio
async def test_mark_all_read(client, notif_data):
    resp = await client.patch("/api/v1/notifications/read-all", headers=notif_data["headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["count"] == 2

    # Verify all are now read
    resp2 = await client.get("/api/v1/notifications", headers=notif_data["headers"])
    assert resp2.json()["unread_count"] == 0


@pytest.mark.asyncio
async def test_notification_tenant_isolation(client, notif_data):
    """User from another tenant should not see these notifications."""
    async with TestSession() as session:
        other_headers, _, _ = await _create_user(session, "other@corp.com", "admin", "Other Corp")
    resp = await client.get("/api/v1/notifications", headers=other_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


@pytest.mark.asyncio
async def test_mark_other_tenant_notification_not_found(client, notif_data):
    """User from another tenant cannot mark-read a notification they don't own."""
    async with TestSession() as session:
        other_headers, _, _ = await _create_user(session, "other2@corp.com", "admin", "Other Corp 2")
    nid = str(notif_data["notification_ids"][0])
    resp = await client.patch(f"/api/v1/notifications/{nid}/read", headers=other_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_notifications_unauthenticated(client):
    resp = await client.get("/api/v1/notifications")
    assert resp.status_code in (401, 403)
