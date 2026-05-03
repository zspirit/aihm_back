"""Tests for /api/v1/tasks endpoints (Phase 4.5 CRM)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.task import Task
from app.models.tenant import Tenant
from app.models.user import User


pytestmark = pytest.mark.asyncio


# ─── POST /tasks ──────────────────────────────────────────────────────────────


async def test_create_minimal_task(client, admin_data, db_session):
    headers, user, tenant = admin_data
    res = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "Call hiring manager"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["title"] == "Call hiring manager"
    assert body["status"] == "pending"
    assert body["created_by"] == str(user.id)
    assert body["assignee_id"] is None
    assert body["completed_at"] is None

    task = await db_session.get(Task, body["id"])
    assert task is not None
    assert task.tenant_id == tenant.id


async def test_create_task_with_full_payload(client, admin_data, db_session):
    headers, user, _tenant = admin_data
    cand_id = uuid4()
    due = datetime.now(timezone.utc) + timedelta(days=2)
    res = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={
            "title": "Reference check",
            "description": "Call previous manager",
            "entity_type": "candidate",
            "entity_id": str(cand_id),
            "assignee_id": str(user.id),
            "due_date": due.isoformat(),
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["entity_type"] == "candidate"
    assert body["entity_id"] == str(cand_id)
    assert body["assignee_id"] == str(user.id)


async def test_create_rejects_foreign_tenant_assignee(client, admin_data, db_session):
    headers, _user, _tenant = admin_data
    other_tenant = Tenant(name="Other")
    db_session.add(other_tenant)
    await db_session.flush()
    foreign_user = User(
        tenant_id=other_tenant.id, email="x@y.com",
        password_hash="x", full_name="X", role="admin",
    )
    db_session.add(foreign_user)
    await db_session.commit()
    await db_session.refresh(foreign_user)

    res = await client.post(
        "/api/v1/tasks",
        headers=headers,
        json={"title": "x", "assignee_id": str(foreign_user.id)},
    )
    assert res.status_code == 400


async def test_create_validates_empty_title(client, admin_data):
    headers, _, _ = admin_data
    res = await client.post("/api/v1/tasks", headers=headers, json={"title": ""})
    assert res.status_code == 422


async def test_create_requires_auth(client):
    res = await client.post("/api/v1/tasks", json={"title": "x"})
    assert res.status_code in (401, 403)


# ─── GET /tasks (list + filters) ──────────────────────────────────────────────


async def _make_task(db, **kwargs):
    """Direct insertion helper — bypasses the API for setup."""
    t = Task(**kwargs)
    db.add(t)
    await db.flush()
    return t


async def test_list_returns_only_own_tenant(client, admin_data, db_session):
    headers, user, tenant = admin_data
    await _make_task(
        db_session,
        tenant_id=tenant.id, created_by=user.id,
        title="mine",
    )
    other = Tenant(name="Other")
    db_session.add(other)
    await db_session.flush()
    other_user = User(
        tenant_id=other.id, email="o@x.com",
        password_hash="x", full_name="X", role="admin",
    )
    db_session.add(other_user)
    await db_session.flush()
    await _make_task(
        db_session,
        tenant_id=other.id, created_by=other_user.id,
        title="theirs",
    )
    await db_session.commit()

    res = await client.get("/api/v1/tasks", headers=headers)
    assert res.status_code == 200
    titles = [t["title"] for t in res.json()]
    assert titles == ["mine"]


async def test_list_filters_by_status(client, admin_data, db_session):
    headers, user, tenant = admin_data
    await _make_task(db_session, tenant_id=tenant.id, created_by=user.id, title="A", status="pending")
    await _make_task(db_session, tenant_id=tenant.id, created_by=user.id, title="B", status="done")
    await db_session.commit()

    res = await client.get("/api/v1/tasks?status=done", headers=headers)
    assert res.status_code == 200
    titles = [t["title"] for t in res.json()]
    assert titles == ["B"]


async def test_list_filters_by_assignee_me(client, admin_data, db_session):
    """assignee_id='me' returns:
    - tasks explicitly assigned to me, AND
    - unassigned tasks I created (otherwise self-created to-dos with no
      explicit assignee would never appear in 'mine')."""
    headers, user, tenant = admin_data
    other = User(
        tenant_id=tenant.id, email="other@same.com",
        password_hash="x", full_name="X", role="recruiter",
    )
    db_session.add(other)
    await db_session.flush()

    # Explicitly assigned to me — should appear.
    await _make_task(db_session, tenant_id=tenant.id, created_by=user.id,
                     assignee_id=user.id, title="for-me")
    # Assigned to someone else — should NOT appear.
    await _make_task(db_session, tenant_id=tenant.id, created_by=user.id,
                     assignee_id=other.id, title="for-them")
    # Created by me, unassigned — SHOULD appear (was the bug).
    await _make_task(db_session, tenant_id=tenant.id, created_by=user.id,
                     assignee_id=None, title="my-todo")
    # Created by someone else, unassigned — should NOT appear.
    await _make_task(db_session, tenant_id=tenant.id, created_by=other.id,
                     assignee_id=None, title="their-todo")
    await db_session.commit()

    res = await client.get("/api/v1/tasks?assignee_id=me", headers=headers)
    titles = sorted(t["title"] for t in res.json())
    assert titles == ["for-me", "my-todo"]


async def test_list_filters_by_entity(client, admin_data, db_session):
    headers, user, tenant = admin_data
    cand_id = uuid4()
    await _make_task(db_session, tenant_id=tenant.id, created_by=user.id,
                     entity_type="candidate", entity_id=cand_id, title="A")
    await _make_task(db_session, tenant_id=tenant.id, created_by=user.id,
                     entity_type="position", entity_id=uuid4(), title="B")
    await db_session.commit()

    res = await client.get(
        f"/api/v1/tasks?entity_type=candidate&entity_id={cand_id}",
        headers=headers,
    )
    titles = [t["title"] for t in res.json()]
    assert titles == ["A"]


async def test_list_overdue_filter(client, admin_data, db_session):
    headers, user, tenant = admin_data
    past = datetime.now(timezone.utc) - timedelta(days=1)
    future = datetime.now(timezone.utc) + timedelta(days=1)

    await _make_task(db_session, tenant_id=tenant.id, created_by=user.id,
                     title="overdue", status="pending", due_date=past)
    await _make_task(db_session, tenant_id=tenant.id, created_by=user.id,
                     title="future", status="pending", due_date=future)
    # Done tasks shouldn't appear even if past due.
    await _make_task(db_session, tenant_id=tenant.id, created_by=user.id,
                     title="done-old", status="done", due_date=past)
    await db_session.commit()

    res = await client.get("/api/v1/tasks?overdue=true", headers=headers)
    titles = sorted(t["title"] for t in res.json())
    assert titles == ["overdue"]


# ─── GET /tasks/{id} ──────────────────────────────────────────────────────────


async def test_get_returns_task(client, admin_data, db_session):
    headers, user, tenant = admin_data
    t = await _make_task(db_session, tenant_id=tenant.id, created_by=user.id, title="get me")
    await db_session.commit()

    res = await client.get(f"/api/v1/tasks/{t.id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["title"] == "get me"


async def test_get_unknown_returns_404(client, admin_data):
    headers, _, _ = admin_data
    res = await client.get(f"/api/v1/tasks/{uuid4()}", headers=headers)
    assert res.status_code == 404


# ─── PATCH /tasks/{id} ────────────────────────────────────────────────────────


async def test_patch_marks_done_sets_completed_at(client, admin_data, db_session):
    headers, user, tenant = admin_data
    t = await _make_task(db_session, tenant_id=tenant.id, created_by=user.id,
                         title="x", status="pending")
    await db_session.commit()

    res = await client.patch(
        f"/api/v1/tasks/{t.id}",
        headers=headers,
        json={"status": "done"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "done"
    assert body["completed_at"] is not None


async def test_patch_reopen_clears_completed_at(client, admin_data, db_session):
    headers, user, tenant = admin_data
    t = await _make_task(
        db_session,
        tenant_id=tenant.id, created_by=user.id,
        title="x", status="done",
        completed_at=datetime.now(timezone.utc),
    )
    await db_session.commit()

    res = await client.patch(
        f"/api/v1/tasks/{t.id}",
        headers=headers,
        json={"status": "pending"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "pending"
    assert body["completed_at"] is None


async def test_patch_rejects_invalid_status(client, admin_data, db_session):
    headers, user, tenant = admin_data
    t = await _make_task(db_session, tenant_id=tenant.id, created_by=user.id, title="x")
    await db_session.commit()

    res = await client.patch(
        f"/api/v1/tasks/{t.id}",
        headers=headers,
        json={"status": "in_progress"},  # not in {pending, done, cancelled}
    )
    assert res.status_code == 422


async def test_patch_unknown_returns_404(client, admin_data):
    headers, _, _ = admin_data
    res = await client.patch(
        f"/api/v1/tasks/{uuid4()}",
        headers=headers,
        json={"title": "y"},
    )
    assert res.status_code == 404


# ─── DELETE /tasks/{id} ───────────────────────────────────────────────────────


async def test_delete_removes_row(client, admin_data, db_session):
    headers, user, tenant = admin_data
    t = await _make_task(db_session, tenant_id=tenant.id, created_by=user.id, title="bye")
    await db_session.commit()
    task_id = t.id

    res = await client.delete(f"/api/v1/tasks/{task_id}", headers=headers)
    assert res.status_code == 204

    db_session.expunge_all()
    found = (await db_session.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    assert found is None
