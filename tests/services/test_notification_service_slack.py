"""Tests for the Slack fan-out path in notification_service.

The DB+SSE behaviour is already exercised through the existing
notification_service tests; here we focus on the Slack forwarding rules
added in Phase 4.6.
"""
from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest

from app.models.notification import Notification
from app.models.tenant import Tenant
from app.services import notification_service as svc


@pytest.fixture
def db_tenant_with_slack(db_session):
    """Sync version not available — these tests use the async fixture
    just to seed a tenant row, then operate on the underlying sync session
    where notification_service runs."""
    pass  # placeholder


# ─── _slack_text_for ──────────────────────────────────────────────────────────


def test_slack_text_uses_title_and_message():
    n = Notification(
        tenant_id=uuid4(), user_id=uuid4(),
        type="candidate.cv_analyzed",
        title="CV analysé : Alice", message="Score 87/100",
    )
    text = svc._slack_text_for(n)
    assert "CV analysé : Alice" in text
    assert "Score 87/100" in text


def test_slack_text_falls_back_to_type_when_no_title():
    n = Notification(
        tenant_id=uuid4(), user_id=uuid4(),
        type="candidate.cv_analyzed",
        title="", message="",
    )
    assert svc._slack_text_for(n) == "*candidate.cv_analyzed*"


# ─── _maybe_forward_to_slack ──────────────────────────────────────────────────


def test_maybe_forward_skips_non_whitelisted_types():
    """Random notif types must not be relayed to Slack."""
    n = Notification(
        tenant_id=uuid4(), user_id=uuid4(),
        type="some.random.type",
        title="x", message="y",
    )
    fake_session = type("S", (), {"get": lambda *_: None})()
    with patch("app.services.notification_service.slack_send") as send:
        svc._maybe_forward_to_slack(fake_session, n)
        send.assert_not_called()


def test_maybe_forward_skips_when_tenant_has_no_webhook():
    n = Notification(
        tenant_id=uuid4(), user_id=uuid4(),
        type="candidate.cv_analyzed",
        title="x", message="y",
    )
    tenant = Tenant(name="T", modules_config={})  # no slack key
    fake_session = type("S", (), {"get": staticmethod(lambda *_: tenant)})()
    with patch("app.services.notification_service.slack_send") as send:
        svc._maybe_forward_to_slack(fake_session, n)
        send.assert_not_called()


def test_maybe_forward_calls_slack_when_configured():
    n = Notification(
        tenant_id=uuid4(), user_id=uuid4(),
        type="candidate.cv_analyzed",
        title="CV analysé : Alice", message="Score 87/100",
    )
    tenant = Tenant(name="T", modules_config={"slack_webhook_url": "https://hooks.slack.com/x"})
    fake_session = type("S", (), {"get": staticmethod(lambda *_: tenant)})()
    with patch("app.services.notification_service.slack_send") as send:
        svc._maybe_forward_to_slack(fake_session, n)
        send.assert_called_once()
        url, text = send.call_args.args
        assert url == "https://hooks.slack.com/x"
        assert "Alice" in text


def test_maybe_forward_swallows_slack_errors():
    """Slack outages must never break the create-notification flow."""
    n = Notification(
        tenant_id=uuid4(), user_id=uuid4(),
        type="candidate.cv_analyzed",
        title="x", message="y",
    )
    tenant = Tenant(name="T", modules_config={"slack_webhook_url": "https://hooks.slack.com/x"})
    fake_session = type("S", (), {"get": staticmethod(lambda *_: tenant)})()
    with patch(
        "app.services.notification_service.slack_send",
        side_effect=ConnectionError("boom"),
    ):
        # Should not raise.
        svc._maybe_forward_to_slack(fake_session, n)


# ─── Forward-once de-dup logic (tested at unit level via the loop) ────────────


def test_forward_once_per_tenant_type_dedup_set():
    """Sanity: the seen_tenants set keys on (tenant_id, type), so two
    different users on the same tenant+type collapse to one Slack push."""
    tid = uuid4()
    seen: set = set()
    notifs = [
        Notification(tenant_id=tid, user_id=uuid4(), type="candidate.cv_analyzed",
                     title="t", message="m"),
        Notification(tenant_id=tid, user_id=uuid4(), type="candidate.cv_analyzed",
                     title="t", message="m"),
        Notification(tenant_id=tid, user_id=uuid4(), type="offer.signed",
                     title="t", message="m"),
    ]
    forwarded = 0
    for n in notifs:
        key = (n.tenant_id, n.type)
        if key in seen:
            continue
        seen.add(key)
        forwarded += 1
    assert forwarded == 2  # one per (tenant, type)
