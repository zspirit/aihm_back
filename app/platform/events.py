"""Platform event bus — inter-module communication for the modular monolith.

Modules never import each other; they talk through events. Each emitted event
is also persisted to ``domain_events`` for traceability and future webhook
replay. Dispatch is best-effort: a failing handler is logged and never breaks
the emitter (production would add retry off the domain_events log).
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Awaitable, Callable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain_event import DomainEvent

logger = structlog.get_logger(__name__)

Handler = Callable[..., Awaitable[None]]


class EventBus:
    """Minimal in-process pub/sub. One instance shared process-wide."""

    def __init__(self) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: Handler) -> None:
        if handler not in self._subs[event_type]:
            self._subs[event_type].append(handler)

    def subscribers(self, event_type: str) -> list[Handler]:
        return list(self._subs.get(event_type, []))

    async def emit(
        self,
        event_type: str,
        *,
        payload: dict,
        db: AsyncSession,
        tenant_id: uuid.UUID,
        source_module: str,
    ) -> None:
        """Persist the event then dispatch to subscribed handlers in-process.

        Runs inside the caller's transaction/session so handler writes commit
        atomically with the originating change.
        """
        db.add(
            DomainEvent(
                tenant_id=tenant_id,
                type=event_type,
                source_module=source_module,
                payload=payload,
            )
        )
        await db.flush()

        for handler in self._subs.get(event_type, []):
            try:
                await handler(payload=payload, db=db, tenant_id=tenant_id)
            except Exception:  # best-effort: never break the emitter
                logger.exception(
                    "event_handler_failed",
                    event_type=event_type,
                    handler=getattr(handler, "__name__", str(handler)),
                )


event_bus = EventBus()
