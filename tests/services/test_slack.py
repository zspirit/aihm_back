"""Unit tests for the Slack outbound notifications service."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import slack as slack_svc


# ─── format helpers ───────────────────────────────────────────────────────────


def test_format_includes_text_fallback_and_blocks():
    payload = slack_svc._format_block("Hello", {"Status": "ok"})
    assert payload["text"] == "Hello"
    assert payload["blocks"][0]["text"]["text"] == "Hello"
    # Fields are mrkdwn formatted as *Key*\nValue
    fields = payload["blocks"][1]["fields"]
    assert any("*Status*" in f["text"] and "ok" in f["text"] for f in fields)


def test_format_omits_fields_block_when_empty():
    payload = slack_svc._format_block("Hello")
    assert len(payload["blocks"]) == 1


# ─── send_message_sync ────────────────────────────────────────────────────────


def test_send_message_sync_returns_false_for_empty_url():
    assert slack_svc.send_message_sync("", "hi") is False


def test_send_message_sync_returns_true_on_2xx():
    fake = MagicMock()
    fake.status_code = 200
    mock_client = MagicMock()
    mock_client.post = MagicMock(return_value=fake)
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)

    with patch("httpx.Client", return_value=mock_client):
        assert slack_svc.send_message_sync("https://hooks.slack.com/x", "hi") is True


def test_send_message_sync_returns_false_on_5xx():
    fake = MagicMock()
    fake.status_code = 500
    mock_client = MagicMock()
    mock_client.post = MagicMock(return_value=fake)
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)

    with patch("httpx.Client", return_value=mock_client):
        assert slack_svc.send_message_sync("https://hooks.slack.com/x", "hi") is False


def test_send_message_sync_swallows_exceptions():
    """fire-and-forget: a network error must not propagate."""
    mock_client = MagicMock()
    mock_client.post = MagicMock(side_effect=ConnectionError("no route"))
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)

    with patch("httpx.Client", return_value=mock_client):
        assert slack_svc.send_message_sync("https://hooks.slack.com/x", "hi") is False


# ─── send_message_async ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_message_async_returns_false_for_empty_url():
    assert await slack_svc.send_message_async("", "hi") is False


@pytest.mark.asyncio
async def test_send_message_async_success():
    fake = MagicMock()
    fake.status_code = 200
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=fake)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        assert await slack_svc.send_message_async("https://hooks.slack.com/x", "hi") is True


# ─── send_message_strict ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_message_strict_raises_when_no_url():
    with pytest.raises(slack_svc.SlackError, match="no webhook URL"):
        await slack_svc.send_message_strict("", "hi")


@pytest.mark.asyncio
async def test_send_message_strict_raises_on_non_2xx():
    fake = MagicMock()
    fake.status_code = 404
    fake.text = "no such webhook"
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=fake)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(slack_svc.SlackError, match="404"):
            await slack_svc.send_message_strict("https://hooks.slack.com/x", "hi")


# ─── event helpers ────────────────────────────────────────────────────────────


def test_notify_new_candidate_calls_send_message_sync():
    with patch("app.services.slack.send_message_sync", return_value=True) as send:
        result = slack_svc.notify_new_candidate("url", "Alice", "Backend Dev")
        assert result is True
        send.assert_called_once()
        text, fields = send.call_args.args[1], send.call_args.args[2]
        assert "Alice" in text
        assert fields["Position"] == "Backend Dev"


def test_notify_offer_signed_uses_check_emoji():
    with patch("app.services.slack.send_message_sync", return_value=True) as send:
        slack_svc.notify_offer_signed("url", "Bob", "PM")
        text = send.call_args.args[1]
        assert "Offer signed" in text
        assert "Bob" in text


def test_notify_cv_analyzed_includes_score():
    with patch("app.services.slack.send_message_sync", return_value=True) as send:
        slack_svc.notify_cv_analyzed("url", "Charlie", 87.4)
        text = send.call_args.args[1]
        assert "Charlie" in text
        # round() gives 87
        assert "87" in text
