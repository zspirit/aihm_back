"""Tests for webhook dispatch service."""
import hashlib
import hmac
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.webhooks import _sign_payload, WEBHOOK_EVENTS, dispatch_event


def test_sign_payload():
    payload = b'{"event":"test"}'
    secret = "mysecret"
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert _sign_payload(payload, secret) == expected


def test_webhook_events_defined():
    assert "consent.given" in WEBHOOK_EVENTS
    assert "interview.completed" in WEBHOOK_EVENTS
    assert "report.ready" in WEBHOOK_EVENTS
    assert "cv.scored" in WEBHOOK_EVENTS


@pytest.mark.asyncio
async def test_dispatch_no_subscribers():
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute.return_value = mock_result

    count = await dispatch_event(
        db, tenant_id=uuid.uuid4(), event="consent.given", data={"id": "123"}
    )
    assert count == 0


@pytest.mark.asyncio
async def test_dispatch_sends_to_matching_subscribers():
    tenant_id = uuid.uuid4()

    sub = MagicMock()
    sub.url = "https://hooks.example.com/test"
    sub.secret = "s3cret"
    sub.events = ["consent.given", "cv.scored"]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [sub]

    db = AsyncMock()
    db.execute.return_value = mock_result

    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("app.services.webhooks.httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.post.return_value = mock_response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        count = await dispatch_event(
            db, tenant_id=tenant_id, event="consent.given", data={"id": "x"}
        )

    assert count == 1
    client_instance.post.assert_called_once()
    call_kwargs = client_instance.post.call_args
    assert call_kwargs[0][0] == "https://hooks.example.com/test"
    assert "X-AIHM-Signature" in call_kwargs[1]["headers"]


@pytest.mark.asyncio
async def test_dispatch_skips_non_matching_events():
    sub = MagicMock()
    sub.url = "https://hooks.example.com/test"
    sub.secret = "s3cret"
    sub.events = ["report.ready"]  # Not matching consent.given

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [sub]

    db = AsyncMock()
    db.execute.return_value = mock_result

    count = await dispatch_event(
        db, tenant_id=uuid.uuid4(), event="consent.given", data={}
    )
    assert count == 0


@pytest.mark.asyncio
async def test_dispatch_handles_http_error():
    sub = MagicMock()
    sub.url = "https://hooks.example.com/fail"
    sub.secret = "s3cret"
    sub.events = ["cv.scored"]

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [sub]

    db = AsyncMock()
    db.execute.return_value = mock_result

    with patch("app.services.webhooks.httpx.AsyncClient") as MockClient, \
         patch("app.services.webhooks.logger") as mock_logger:
        client_instance = AsyncMock()
        client_instance.post.side_effect = ConnectionError("timeout")
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        count = await dispatch_event(
            db, tenant_id=uuid.uuid4(), event="cv.scored", data={}
        )

    assert count == 0
    mock_logger.warning.assert_called_once()
