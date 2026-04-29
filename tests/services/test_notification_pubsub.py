"""Tests for the notification pub/sub bus (Redis SSE backend)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services import notification_pubsub as nps


@pytest.fixture(autouse=True)
def _clear_lru_caches():
    """Drop the singleton clients so each test gets fresh mocks."""
    nps._sync_client.cache_clear()
    nps._async_client.cache_clear()
    yield
    nps._sync_client.cache_clear()
    nps._async_client.cache_clear()


# ─── URL & channel helpers ────────────────────────────────────────────────────


def test_redis_url_forces_db_4():
    with patch("app.services.notification_pubsub.get_settings") as gs:
        gs.return_value.REDIS_URL = "redis://:pwd@redis:6379/0"
        assert nps._redis_url() == "redis://:pwd@redis:6379/4"


def test_redis_url_overrides_existing_db_number():
    with patch("app.services.notification_pubsub.get_settings") as gs:
        gs.return_value.REDIS_URL = "redis://:pwd@host:6379/9"
        assert nps._redis_url() == "redis://:pwd@host:6379/4"


def test_redis_url_with_explicit_db():
    with patch("app.services.notification_pubsub.get_settings") as gs:
        gs.return_value.REDIS_URL = "redis://:pwd@host:6379/0"
        assert nps._redis_url(db=2) == "redis://:pwd@host:6379/2"


def test_user_channel_format():
    uid = uuid4()
    assert nps._user_channel(uid) == f"notif:user:{uid}"
    assert nps._user_channel("abc-123") == "notif:user:abc-123"


def test_tenant_channel_format():
    tid = uuid4()
    assert nps._tenant_channel(tid) == f"notif:tenant:{tid}"


# ─── publish_user_sync ────────────────────────────────────────────────────────


def test_publish_user_sync_sends_json_payload():
    fake_client = MagicMock()
    fake_client.publish.return_value = 3  # 3 subscribers
    with patch("app.services.notification_pubsub._sync_client", return_value=fake_client):
        uid = uuid4()
        result = nps.publish_user_sync(uid, {"type": "test", "id": "x"})
        assert result == 3
        fake_client.publish.assert_called_once()
        channel, raw = fake_client.publish.call_args.args
        assert channel == f"notif:user:{uid}"
        assert json.loads(raw) == {"type": "test", "id": "x"}


def test_publish_user_sync_swallows_exceptions():
    """fire-and-forget: a Redis outage must not break the calling worker."""
    fake_client = MagicMock()
    fake_client.publish.side_effect = ConnectionError("redis down")
    with patch("app.services.notification_pubsub._sync_client", return_value=fake_client):
        result = nps.publish_user_sync(uuid4(), {"x": 1})
        assert result == 0


def test_publish_user_sync_serializes_uuids_in_payload():
    """default=str on json.dumps must handle UUID values inside the payload."""
    fake_client = MagicMock()
    fake_client.publish.return_value = 1
    nested_uuid = uuid4()
    with patch("app.services.notification_pubsub._sync_client", return_value=fake_client):
        nps.publish_user_sync(uuid4(), {"candidate_id": nested_uuid})
        raw = fake_client.publish.call_args.args[1]
        decoded = json.loads(raw)
        assert decoded["candidate_id"] == str(nested_uuid)


# ─── publish_tenant_sync ──────────────────────────────────────────────────────


def test_publish_tenant_sync_uses_tenant_channel():
    fake_client = MagicMock()
    fake_client.publish.return_value = 5
    with patch("app.services.notification_pubsub._sync_client", return_value=fake_client):
        tid = uuid4()
        result = nps.publish_tenant_sync(tid, {"type": "broadcast"})
        assert result == 5
        channel, _ = fake_client.publish.call_args.args
        assert channel == f"notif:tenant:{tid}"


def test_publish_tenant_sync_swallows_exceptions():
    fake_client = MagicMock()
    fake_client.publish.side_effect = RuntimeError("kaboom")
    with patch("app.services.notification_pubsub._sync_client", return_value=fake_client):
        assert nps.publish_tenant_sync(uuid4(), {"x": 1}) == 0


# ─── publish_*_async ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_user_async_sends_payload():
    fake_client = MagicMock()
    fake_client.publish = AsyncMock(return_value=2)
    with patch("app.services.notification_pubsub._async_client", return_value=fake_client):
        uid = uuid4()
        result = await nps.publish_user_async(uid, {"type": "ping"})
        assert result == 2
        fake_client.publish.assert_awaited_once()
        channel, raw = fake_client.publish.call_args.args
        assert channel == f"notif:user:{uid}"
        assert json.loads(raw) == {"type": "ping"}


@pytest.mark.asyncio
async def test_publish_user_async_swallows_exceptions():
    fake_client = MagicMock()
    fake_client.publish = AsyncMock(side_effect=ConnectionError("down"))
    with patch("app.services.notification_pubsub._async_client", return_value=fake_client):
        assert await nps.publish_user_async(uuid4(), {"x": 1}) == 0


@pytest.mark.asyncio
async def test_publish_tenant_async_uses_tenant_channel():
    fake_client = MagicMock()
    fake_client.publish = AsyncMock(return_value=4)
    with patch("app.services.notification_pubsub._async_client", return_value=fake_client):
        tid = uuid4()
        result = await nps.publish_tenant_async(tid, {})
        assert result == 4
        channel, _ = fake_client.publish.call_args.args
        assert channel == f"notif:tenant:{tid}"


@pytest.mark.asyncio
async def test_publish_tenant_async_swallows_exceptions():
    fake_client = MagicMock()
    fake_client.publish = AsyncMock(side_effect=RuntimeError("nope"))
    with patch("app.services.notification_pubsub._async_client", return_value=fake_client):
        assert await nps.publish_tenant_async(uuid4(), {"x": 1}) == 0


# ─── subscribe (async context manager) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_subscribe_subscribes_and_unsubscribes():
    fake_pubsub = MagicMock()
    fake_pubsub.subscribe = AsyncMock()
    fake_pubsub.unsubscribe = AsyncMock()
    fake_pubsub.aclose = AsyncMock()

    fake_client = MagicMock()
    fake_client.pubsub = MagicMock(return_value=fake_pubsub)

    with patch("app.services.notification_pubsub._async_client", return_value=fake_client):
        channels = ["notif:user:abc", "notif:tenant:xyz"]
        async with nps.subscribe(channels) as ps:
            assert ps is fake_pubsub
            fake_pubsub.subscribe.assert_awaited_once_with(*channels)

        fake_pubsub.unsubscribe.assert_awaited_once_with(*channels)
        fake_pubsub.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_subscribe_cleans_up_on_exception():
    """If the body raises, we still unsubscribe + close to avoid leaking redis connections."""
    fake_pubsub = MagicMock()
    fake_pubsub.subscribe = AsyncMock()
    fake_pubsub.unsubscribe = AsyncMock()
    fake_pubsub.aclose = AsyncMock()

    fake_client = MagicMock()
    fake_client.pubsub = MagicMock(return_value=fake_pubsub)

    with patch("app.services.notification_pubsub._async_client", return_value=fake_client):
        with pytest.raises(ValueError):
            async with nps.subscribe(["c1"]):
                raise ValueError("boom")

        fake_pubsub.unsubscribe.assert_awaited_once_with("c1")
        fake_pubsub.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_subscribe_tolerates_unsubscribe_errors_during_cleanup():
    """Cleanup errors must not propagate (they would mask the real exception)."""
    fake_pubsub = MagicMock()
    fake_pubsub.subscribe = AsyncMock()
    fake_pubsub.unsubscribe = AsyncMock(side_effect=RuntimeError("conn lost"))
    fake_pubsub.aclose = AsyncMock(side_effect=RuntimeError("already closed"))

    fake_client = MagicMock()
    fake_client.pubsub = MagicMock(return_value=fake_pubsub)

    with patch("app.services.notification_pubsub._async_client", return_value=fake_client):
        async with nps.subscribe(["c1"]) as ps:
            assert ps is fake_pubsub
        # No exception bubbles up — cleanup errors are silenced.
