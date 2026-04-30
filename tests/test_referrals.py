"""Tests for referral endpoints (Phase 4.3 V1_ROADMAP)."""
from __future__ import annotations

import io

import pytest
from sqlalchemy import select

from app.models.application import Application
from app.models.candidate import Candidate
from app.models.position import Position
from app.models.user import User


pytestmark = pytest.mark.asyncio


# ─── GET /me/referral-link ────────────────────────────────────────────────────


async def test_my_referral_link_generates_token_on_first_call(client, admin_data):
    headers, user, _tenant = admin_data
    # User starts with no referral_token (default state).
    assert getattr(user, "referral_token", None) in (None, "")

    res = await client.get("/api/v1/me/referral-link", headers=headers)
    assert res.status_code == 200

    body = res.json()
    assert "token" in body
    assert len(body["token"]) >= 24  # secrets.token_urlsafe(24) → ≥32 chars
    assert body["url_template"] == f"/refer/{body['token']}"


async def test_my_referral_link_is_idempotent(client, admin_data, db_session):
    """Calling the endpoint twice must return the same token."""
    headers, user, _tenant = admin_data

    first = await client.get("/api/v1/me/referral-link", headers=headers)
    second = await client.get("/api/v1/me/referral-link", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["token"] == second.json()["token"]

    # And it's persisted on the user row. The API uses its own session, so
    # re-query (don't reuse the cached User object from the fixture).
    refreshed = (
        await db_session.execute(select(User).where(User.id == user.id))
    ).scalar_one()
    assert refreshed.referral_token == first.json()["token"]


async def test_my_referral_link_requires_auth(client):
    res = await client.get("/api/v1/me/referral-link")
    assert res.status_code in (401, 403)


# ─── GET /public/refer/{token}/info ───────────────────────────────────────────


async def test_referral_info_returns_referrer_name(client, admin_data):
    headers, user, tenant = admin_data
    # Generate a token via the authenticated endpoint.
    token = (await client.get("/api/v1/me/referral-link", headers=headers)).json()["token"]

    res = await client.get(f"/api/v1/public/refer/{token}/info")
    assert res.status_code == 200

    body = res.json()
    # _create_user gives full_name = "Admin User"
    assert body["referrer_name"] == user.full_name
    assert body["tenant_id"] == str(tenant.id)


async def test_referral_info_falls_back_to_email_local_part(client, db_session, admin_data):
    """If full_name is empty/None, return the email's local part instead."""
    headers, user, _ = admin_data
    token = (await client.get("/api/v1/me/referral-link", headers=headers)).json()["token"]

    # Wipe full_name so the fallback path runs.
    user.full_name = ""
    await db_session.commit()

    res = await client.get(f"/api/v1/public/refer/{token}/info")
    assert res.status_code == 200
    assert res.json()["referrer_name"] == user.email.split("@")[0]


async def test_referral_info_unknown_token_returns_404(client):
    res = await client.get("/api/v1/public/refer/this-token-does-not-exist/info")
    assert res.status_code == 404
    assert "introuvable" in res.json()["detail"].lower()


# ─── POST /public/refer/{token}/apply ─────────────────────────────────────────


async def test_referral_apply_creates_candidate_without_position(
    client, admin_data, db_session
):
    headers, _user, tenant = admin_data
    token = (await client.get("/api/v1/me/referral-link", headers=headers)).json()["token"]

    res = await client.post(
        f"/api/v1/public/refer/{token}/apply",
        data={"name": "John Referral", "email": "john@example.com"},
    )
    assert res.status_code == 200

    body = res.json()
    assert body["status"] == "received"
    assert "candidate_id" in body

    cand = await db_session.get(Candidate, body["candidate_id"])
    assert cand is not None
    assert cand.tenant_id == tenant.id
    assert cand.name == "John Referral"
    assert cand.email == "john@example.com"
    assert cand.pipeline_status == "new"

    # No Application row when position_id is omitted.
    apps = (
        await db_session.execute(select(Application).where(Application.candidate_id == cand.id))
    ).scalars().all()
    assert apps == []


async def test_referral_apply_with_position_creates_application(
    client, admin_data, db_session
):
    headers, user, tenant = admin_data
    token = (await client.get("/api/v1/me/referral-link", headers=headers)).json()["token"]

    # Create a position in the same tenant.
    pos = Position(
        tenant_id=tenant.id,
        title="Backend Dev",
        description="x",
        required_skills=[],
        seniority_level="mid",
        status="active",
        created_by=user.id,
    )
    db_session.add(pos)
    await db_session.commit()
    await db_session.refresh(pos)

    res = await client.post(
        f"/api/v1/public/refer/{token}/apply",
        data={
            "name": "Jane",
            "email": "jane@example.com",
            "position_id": str(pos.id),
            "cover_letter": "I'm motivated.",
        },
    )
    assert res.status_code == 200

    cand_id = res.json()["candidate_id"]
    apps = (
        await db_session.execute(select(Application).where(Application.candidate_id == cand_id))
    ).scalars().all()
    assert len(apps) == 1
    app = apps[0]
    assert app.position_id == pos.id
    assert app.source == "referral"
    assert app.referrer_user_id == user.id
    assert app.tenant_id == tenant.id

    # cover_letter was stashed in cv_parsed_data.
    cand = await db_session.get(Candidate, cand_id)
    assert cand.cv_parsed_data == {"cover_letter": "I'm motivated."}


async def test_referral_apply_with_foreign_tenant_position_skips_application(
    client, admin_data, db_session
):
    """Position must belong to the referrer's tenant — otherwise no Application
    row is created (but the Candidate still is, in the referrer's tenant)."""
    headers, _user, tenant = admin_data
    token = (await client.get("/api/v1/me/referral-link", headers=headers)).json()["token"]

    # Create a position in ANOTHER tenant.
    from app.models.tenant import Tenant
    other_tenant = Tenant(name="Other Corp")
    db_session.add(other_tenant)
    await db_session.flush()
    other_user = User(
        tenant_id=other_tenant.id,
        email="other@x.com",
        password_hash="x",
        full_name="Other",
        role="admin",
    )
    db_session.add(other_user)
    await db_session.flush()
    foreign_pos = Position(
        tenant_id=other_tenant.id,
        title="Foreign role",
        description="x",
        required_skills=[],
        seniority_level="mid",
        status="active",
        created_by=other_user.id,
    )
    db_session.add(foreign_pos)
    await db_session.commit()
    await db_session.refresh(foreign_pos)

    res = await client.post(
        f"/api/v1/public/refer/{token}/apply",
        data={"name": "Jane", "email": "jane@example.com", "position_id": str(foreign_pos.id)},
    )
    assert res.status_code == 200
    cand_id = res.json()["candidate_id"]

    # Candidate is in the referrer's tenant, not the foreign one.
    cand = await db_session.get(Candidate, cand_id)
    assert cand.tenant_id == tenant.id

    # No Application created for the foreign position.
    apps = (
        await db_session.execute(select(Application).where(Application.candidate_id == cand_id))
    ).scalars().all()
    assert apps == []


async def test_referral_apply_unknown_token_returns_404(client):
    res = await client.post(
        "/api/v1/public/refer/nonexistent-token/apply",
        data={"name": "X", "email": "x@x.com"},
    )
    assert res.status_code == 404


async def test_referral_apply_validates_email_format(client, admin_data):
    headers, _user, _tenant = admin_data
    token = (await client.get("/api/v1/me/referral-link", headers=headers)).json()["token"]

    res = await client.post(
        f"/api/v1/public/refer/{token}/apply",
        data={"name": "X", "email": "not-an-email"},
    )
    # Pydantic EmailStr rejects malformed emails before reaching the handler.
    assert res.status_code == 422
