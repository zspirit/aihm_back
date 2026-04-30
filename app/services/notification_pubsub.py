"""Notification real-time pub/sub bus (Redis).

Pattern :
- Source de vérité = table `notifications` (Postgres). Toujours INSERT d'abord.
- Push opportuniste = Redis pub/sub. Si le client SSE est connecté, il reçoit
  l'event en < 100 ms. Si offline, il rattrape via GET /notifications au reconnect.

Canaux :
- `notif:user:{user_id}`     → notif personnelle
- `notif:tenant:{tenant_id}` → broadcast tous les users du tenant

Côté worker Celery (sync) : appeler `publish_user_sync` / `publish_tenant_sync`.
Côté FastAPI (async) : `subscribe(channels)` est un async generator.

Choix techniques :
- DB Redis dédiée (4) pour ne pas polluer Celery (broker=1, result=2) ni le cache (0).
- JSON serialisation (pas de pickle, anti-RCE).
- Singletons clients (sync + async) cachés via lru_cache pour éviter la re-connexion.
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any, AsyncIterator
from uuid import UUID

import redis  # sync
import redis.asyncio as aioredis  # async

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# DB dédiée pour le pubsub notifs (ne collide pas avec celery broker/result/cache)
_PUBSUB_DB = 4


def _redis_url(db: int = _PUBSUB_DB) -> str:
    """Force la DB 4 sur l'URL Redis configurée."""
    base = get_settings().REDIS_URL.rsplit("/", 1)[0]
    return f"{base}/{db}"


@lru_cache(maxsize=1)
def _sync_client() -> redis.Redis:
    """Client sync singleton pour les workers Celery."""
    return redis.from_url(_redis_url(), decode_responses=True)


@lru_cache(maxsize=1)
def _async_client() -> aioredis.Redis:
    """Client async singleton pour les endpoints FastAPI."""
    return aioredis.from_url(_redis_url(), decode_responses=True)


def _user_channel(user_id: UUID | str) -> str:
    return f"notif:user:{user_id}"


def _tenant_channel(tenant_id: UUID | str) -> str:
    return f"notif:tenant:{tenant_id}"


# ─── Publish (sync — pour workers Celery) ──────────────────────────────────────


def publish_user_sync(user_id: UUID | str, payload: dict[str, Any]) -> int:
    """Publish une notification à un user. Retourne le nombre de subscribers atteints.
    Fire-and-forget : ne raise jamais (le DB INSERT est la source de vérité)."""
    try:
        return _sync_client().publish(_user_channel(user_id), json.dumps(payload, default=str))
    except Exception:
        logger.warning("notif_pubsub_publish_user_failed", exc_info=True)
        return 0


def publish_tenant_sync(tenant_id: UUID | str, payload: dict[str, Any]) -> int:
    """Broadcast à tous les subscribers du tenant. Fire-and-forget."""
    try:
        return _sync_client().publish(_tenant_channel(tenant_id), json.dumps(payload, default=str))
    except Exception:
        logger.warning("notif_pubsub_publish_tenant_failed", exc_info=True)
        return 0


# ─── Subscribe (async — pour endpoint SSE) ─────────────────────────────────────


@asynccontextmanager
async def subscribe(channels: list[str]) -> AsyncIterator[Any]:
    """Context manager qui yield un pubsub abonné aux canaux donnés.

    Usage :
        async with subscribe([f"notif:user:{uid}", f"notif:tenant:{tid}"]) as ps:
            async for message in ps.listen():
                if message['type'] == 'message':
                    payload = json.loads(message['data'])
                    yield payload  # vers le client SSE
    """
    client = _async_client()
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    try:
        await pubsub.subscribe(*channels)
        yield pubsub
    finally:
        try:
            await pubsub.unsubscribe(*channels)
        except Exception:
            pass
        try:
            await pubsub.aclose()
        except Exception:
            pass


# ─── Variantes async pour publish (utile depuis endpoints async qui créent des notifs)


async def publish_user_async(user_id: UUID | str, payload: dict[str, Any]) -> int:
    try:
        return await _async_client().publish(
            _user_channel(user_id), json.dumps(payload, default=str)
        )
    except Exception:
        logger.warning("notif_pubsub_publish_user_async_failed", exc_info=True)
        return 0


async def publish_tenant_async(tenant_id: UUID | str, payload: dict[str, Any]) -> int:
    try:
        return await _async_client().publish(
            _tenant_channel(tenant_id), json.dumps(payload, default=str)
        )
    except Exception:
        logger.warning("notif_pubsub_publish_tenant_async_failed", exc_info=True)
        return 0
