"""Integration tests for /api/v1/calendar/* endpoints (Phase 4.2)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.models.user_integration import UserIntegration
from app.services import calendar_oauth as oauth


pytestmark = pytest.mark.asyncio


# ─── /authorize ───────────────────────────────────────────────────────────────


async def test_google_authorize_returns_url_when_configured(client, admin_data):
    headers, _user, _tenant = admin_data
    with patch("app.services.calendar_oauth.get_settings") as gs:
        gs.return_value.GOOGLE_CLIENT_ID = "test-client"
        gs.return_value.JWT_SECRET_KEY = "s"
        gs.return_value.OAUTH_REDIRECT_BASE_URL = "http://localhost:5173"
        res = await client.post("/api/v1/calendar/oauth/google/authorize", headers=headers)

    assert res.status_code == 200
    body = res.json()
    assert body["provider"] == "google"
    assert body["auth_url"].startswith(oauth.GOOGLE_AUTH_URL)
    assert "client_id=test-client" in body["auth_url"]
    assert "state=" in body["auth_url"]


async def test_google_authorize_503_when_not_configured(client, admin_data):
    headers, _user, _tenant = admin_data
    with patch("app.services.calendar_oauth.get_settings") as gs:
        gs.return_value.GOOGLE_CLIENT_ID = ""
        res = await client.post("/api/v1/calendar/oauth/google/authorize", headers=headers)
    assert res.status_code == 503
    assert "GOOGLE_CLIENT_ID" in res.json()["detail"]


async def test_outlook_authorize_returns_url(client, admin_data):
    headers, _user, _tenant = admin_data
    with patch("app.services.calendar_oauth.get_settings") as gs:
        gs.return_value.MICROSOFT_CLIENT_ID = "ms-test"
        gs.return_value.JWT_SECRET_KEY = "s"
        gs.return_value.OAUTH_REDIRECT_BASE_URL = "http://localhost:5173"
        res = await client.post("/api/v1/calendar/oauth/outlook/authorize", headers=headers)
    assert res.status_code == 200
    assert res.json()["provider"] == "outlook"


async def test_authorize_requires_auth(client):
    res = await client.post("/api/v1/calendar/oauth/google/authorize")
    assert res.status_code in (401, 403)


# ─── /callback ────────────────────────────────────────────────────────────────


async def test_google_callback_rejects_invalid_state(client, admin_data):
    headers, _user, _tenant = admin_data
    res = await client.post(
        "/api/v1/calendar/oauth/google/callback",
        headers=headers,
        json={"code": "some-code", "state": "bogus.state.token"},
    )
    assert res.status_code == 400
    assert "state" in res.json()["detail"].lower()


async def test_google_callback_success_stores_encrypted_integration(
    client, admin_data, db_session
):
    headers, user, _tenant = admin_data

    with patch("app.services.calendar_oauth.get_settings") as gs:
        gs.return_value.GOOGLE_CLIENT_ID = "g-id"
        gs.return_value.GOOGLE_CLIENT_SECRET = "g-sec"
        gs.return_value.JWT_SECRET_KEY = "s"
        gs.return_value.ENCRYPTION_KEY = ""  # plaintext OK in test
        gs.return_value.OAUTH_REDIRECT_BASE_URL = "http://localhost:5173"

        # Forge a valid state for this user.
        state = oauth.make_state(str(user.id), oauth.PROVIDER_GOOGLE)

        with patch(
            "app.api.v1.calendar.exchange_google_code",
            new=AsyncMock(return_value={
                "access_token": "google-AT",
                "refresh_token": "google-RT",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/calendar",
            }),
        ):
            res = await client.post(
                "/api/v1/calendar/oauth/google/callback",
                headers=headers,
                json={"code": "auth-code", "state": state},
            )

    assert res.status_code == 200, res.text
    assert res.json()["status"] == "connected"

    # Row was upserted.
    integ = (
        await db_session.execute(
            select(UserIntegration).where(
                UserIntegration.user_id == user.id,
                UserIntegration.provider == oauth.PROVIDER_GOOGLE,
            )
        )
    ).scalar_one()
    assert integ.status == "active"
    assert integ.access_token_encrypted == "google-AT"  # plaintext (no key in test)
    assert integ.refresh_token_encrypted == "google-RT"
    assert integ.expires_at is not None


async def test_google_callback_502_when_provider_returns_no_token(client, admin_data):
    headers, user, _tenant = admin_data
    with patch("app.services.calendar_oauth.get_settings") as gs:
        gs.return_value.GOOGLE_CLIENT_ID = "g-id"
        gs.return_value.GOOGLE_CLIENT_SECRET = "g-sec"
        gs.return_value.JWT_SECRET_KEY = "s"
        gs.return_value.ENCRYPTION_KEY = ""
        gs.return_value.OAUTH_REDIRECT_BASE_URL = "http://localhost:5173"

        state = oauth.make_state(str(user.id), oauth.PROVIDER_GOOGLE)

        with patch(
            "app.api.v1.calendar.exchange_google_code",
            new=AsyncMock(return_value={"error": "invalid_grant"}),  # no access_token
        ):
            res = await client.post(
                "/api/v1/calendar/oauth/google/callback",
                headers=headers,
                json={"code": "x", "state": state},
            )

    assert res.status_code == 502
    assert "access_token" in res.json()["detail"].lower()


# ─── /status ──────────────────────────────────────────────────────────────────


async def test_status_returns_both_providers_disconnected_by_default(client, admin_data):
    headers, _user, _tenant = admin_data
    res = await client.get("/api/v1/calendar/status", headers=headers)
    assert res.status_code == 200

    by_provider = {row["provider"]: row for row in res.json()}
    assert by_provider["google"]["connected"] is False
    assert by_provider["outlook"]["connected"] is False


async def test_status_reflects_active_integration(client, admin_data, db_session):
    headers, user, tenant = admin_data
    db_session.add(UserIntegration(
        tenant_id=tenant.id,
        user_id=user.id,
        provider=oauth.PROVIDER_GOOGLE,
        access_token_encrypted="x",
        status="active",
        account_email="recruiter@example.com",
    ))
    await db_session.commit()

    res = await client.get("/api/v1/calendar/status", headers=headers)
    assert res.status_code == 200
    by_provider = {row["provider"]: row for row in res.json()}
    assert by_provider["google"]["connected"] is True
    assert by_provider["google"]["account_email"] == "recruiter@example.com"


# ─── DELETE /integrations/{provider} ──────────────────────────────────────────


async def test_disconnect_revokes_integration(client, admin_data, db_session):
    headers, user, tenant = admin_data
    db_session.add(UserIntegration(
        tenant_id=tenant.id,
        user_id=user.id,
        provider=oauth.PROVIDER_GOOGLE,
        access_token_encrypted="some-token",
        refresh_token_encrypted="some-refresh",
        status="active",
    ))
    await db_session.commit()

    res = await client.delete("/api/v1/calendar/integrations/google", headers=headers)
    assert res.status_code == 200
    assert res.json()["status"] == "disconnected"

    integ = (
        await db_session.execute(
            select(UserIntegration).where(
                UserIntegration.user_id == user.id,
                UserIntegration.provider == oauth.PROVIDER_GOOGLE,
            )
        )
    ).scalar_one()
    assert integ.status == "revoked"
    assert integ.access_token_encrypted is None
    assert integ.refresh_token_encrypted is None


async def test_disconnect_unknown_provider_400(client, admin_data):
    headers, _, _ = admin_data
    res = await client.delete("/api/v1/calendar/integrations/notarealprovider", headers=headers)
    assert res.status_code == 400


async def test_disconnect_404_when_no_row(client, admin_data):
    headers, _, _ = admin_data
    res = await client.delete("/api/v1/calendar/integrations/google", headers=headers)
    assert res.status_code == 404
