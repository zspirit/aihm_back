"""Integration tests for /api/v1/integrations/* endpoints (Phase 4.6)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.models.tenant import Tenant


pytestmark = pytest.mark.asyncio


# ─── Slack ────────────────────────────────────────────────────────────────────


async def test_get_slack_unconfigured_returns_null(client, admin_data):
    headers, _user, _tenant = admin_data
    res = await client.get("/api/v1/integrations/slack", headers=headers)
    assert res.status_code == 200
    assert res.json() == {"webhook_url": None}


async def test_put_slack_persists_url(client, admin_data, db_session):
    headers, _user, tenant = admin_data
    url = "https://hooks.slack.com/services/T1/B2/abc"
    res = await client.put(
        "/api/v1/integrations/slack",
        headers=headers,
        json={"webhook_url": url},
    )
    assert res.status_code == 200
    assert res.json()["webhook_url"] == url

    # Persisted on the tenant row.
    db_session.expunge_all()
    refreshed = await db_session.get(Tenant, tenant.id)
    assert refreshed.modules_config.get("slack_webhook_url") == url


async def test_put_slack_validates_url_pattern(client, admin_data):
    headers, _, _ = admin_data
    res = await client.put(
        "/api/v1/integrations/slack",
        headers=headers,
        json={"webhook_url": "https://evil.example.com/x"},
    )
    assert res.status_code == 422  # regex pattern rejects non-Slack URLs


async def test_delete_slack_clears_url(client, admin_data, db_session):
    headers, _user, tenant = admin_data
    # First set it.
    await client.put(
        "/api/v1/integrations/slack",
        headers=headers,
        json={"webhook_url": "https://hooks.slack.com/services/T/B/abc"},
    )
    res = await client.delete("/api/v1/integrations/slack", headers=headers)
    assert res.status_code == 200
    assert res.json()["webhook_url"] is None

    db_session.expunge_all()
    refreshed = await db_session.get(Tenant, tenant.id)
    assert "slack_webhook_url" not in (refreshed.modules_config or {})


async def test_test_slack_400_when_not_configured(client, admin_data):
    headers, _, _ = admin_data
    res = await client.post("/api/v1/integrations/slack/test", headers=headers)
    assert res.status_code == 400


async def test_test_slack_calls_slack_when_configured(client, admin_data):
    headers, _user, _tenant = admin_data
    await client.put(
        "/api/v1/integrations/slack",
        headers=headers,
        json={"webhook_url": "https://hooks.slack.com/services/T/B/abc"},
    )
    with patch(
        "app.api.v1.integrations.slack_svc.send_message_strict",
        new=AsyncMock(return_value=None),
    ) as send:
        res = await client.post("/api/v1/integrations/slack/test", headers=headers)
    assert res.status_code == 200
    send.assert_awaited_once()


async def test_test_slack_502_on_provider_error(client, admin_data):
    from app.services.slack import SlackError
    headers, _, _ = admin_data
    await client.put(
        "/api/v1/integrations/slack",
        headers=headers,
        json={"webhook_url": "https://hooks.slack.com/services/T/B/abc"},
    )
    with patch(
        "app.api.v1.integrations.slack_svc.send_message_strict",
        new=AsyncMock(side_effect=SlackError("404 not found")),
    ):
        res = await client.post("/api/v1/integrations/slack/test", headers=headers)
    assert res.status_code == 502


async def test_slack_endpoints_require_admin(client, viewer_headers):
    """Viewers must not be able to read or write integration config."""
    res = await client.get("/api/v1/integrations/slack", headers=viewer_headers)
    assert res.status_code == 403


# ─── DocuSign ─────────────────────────────────────────────────────────────────


async def test_docusign_status_unconfigured(client, admin_data):
    headers, _, _ = admin_data
    with patch("app.api.v1.integrations.get_settings") as gs:
        gs.return_value.DOCUSIGN_INTEGRATION_KEY = ""
        gs.return_value.DOCUSIGN_USER_ID = ""
        gs.return_value.DOCUSIGN_ACCOUNT_ID = ""
        gs.return_value.DOCUSIGN_PRIVATE_KEY = ""
        gs.return_value.DOCUSIGN_AUTH_HOST = "account-d.docusign.com"
        gs.return_value.DOCUSIGN_API_HOST = "demo.docusign.net"
        res = await client.get("/api/v1/integrations/docusign", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is False
    assert body["account_id"] is None


async def test_docusign_status_configured(client, admin_data):
    headers, _, _ = admin_data
    with patch("app.api.v1.integrations.get_settings") as gs:
        gs.return_value.DOCUSIGN_INTEGRATION_KEY = "ik"
        gs.return_value.DOCUSIGN_USER_ID = "uid"
        gs.return_value.DOCUSIGN_ACCOUNT_ID = "acc-1"
        gs.return_value.DOCUSIGN_PRIVATE_KEY = "key"
        gs.return_value.DOCUSIGN_AUTH_HOST = "account.docusign.com"
        gs.return_value.DOCUSIGN_API_HOST = "www.docusign.net"
        res = await client.get("/api/v1/integrations/docusign", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is True
    assert body["account_id"] == "acc-1"
    assert body["auth_host"] == "account.docusign.com"
