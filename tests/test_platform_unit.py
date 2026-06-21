"""Tests unitaires des primitives plateforme (AUCUNE DB requise).

Logique pure : event bus + résolution d'entitlements, isolés via fakes/mocks.
Le comportement lié à la DB (création Party/facette) est couvert par le test
d'intégration Postgres dans test_platform_poc.py.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.domain_event import DomainEvent
from app.models.entitlement import TenantEntitlement
from app.models.tenant import Tenant
from app.platform.entitlements import is_module_enabled
from app.platform.events import EventBus


class FakeSession:
    """Session minimale : capture les objets ajoutés, flush no-op."""

    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:  # pragma: no cover - trivial
        pass


# ──────────────────────────── EventBus ────────────────────────────

@pytest.mark.asyncio
async def test_subscribe_is_deduplicated():
    bus = EventBus()

    async def h(**_):
        ...

    bus.subscribe("e", h)
    bus.subscribe("e", h)
    assert bus.subscribers("e") == [h]


@pytest.mark.asyncio
async def test_emit_persists_event_and_dispatches():
    bus = EventBus()
    seen = []

    async def handler(*, payload, db, tenant_id):
        seen.append((payload, tenant_id))

    bus.subscribe("ats.candidate.hired", handler)

    db = FakeSession()
    tid = uuid.uuid4()
    await bus.emit(
        "ats.candidate.hired", payload={"x": 1}, db=db, tenant_id=tid, source_module="ats"
    )

    assert len(db.added) == 1
    ev = db.added[0]
    assert isinstance(ev, DomainEvent)
    assert ev.type == "ats.candidate.hired"
    assert ev.source_module == "ats"
    assert seen == [({"x": 1}, tid)]


@pytest.mark.asyncio
async def test_emit_is_best_effort_when_a_handler_raises():
    bus = EventBus()
    calls = []

    async def bad(**_):
        calls.append("bad")
        raise RuntimeError("boom")

    async def good(**_):
        calls.append("good")

    bus.subscribe("e", bad)
    bus.subscribe("e", good)

    # ne doit PAS lever malgré le handler défaillant, et le suivant tourne quand même
    await bus.emit("e", payload={}, db=FakeSession(), tenant_id=uuid.uuid4(), source_module="x")
    assert calls == ["bad", "good"]


@pytest.mark.asyncio
async def test_emit_with_no_subscribers_still_logs_event():
    bus = EventBus()
    db = FakeSession()
    await bus.emit("orphan.event", payload={}, db=db, tenant_id=uuid.uuid4(), source_module="x")
    assert len(db.added) == 1
    assert db.added[0].type == "orphan.event"


# ────────────────────────── Entitlements ──────────────────────────

def _fake_db(entitlement, tenant):
    db = AsyncMock()
    res = MagicMock()
    res.scalar_one_or_none.return_value = entitlement
    db.execute.return_value = res  # awaited -> res
    db.get.return_value = tenant   # awaited -> tenant
    return db


@pytest.mark.asyncio
async def test_entitlement_active_enables():
    db = _fake_db(TenantEntitlement(module_key="timesheet", status="active"), None)
    assert await is_module_enabled(db, uuid.uuid4(), "timesheet") is True


@pytest.mark.asyncio
async def test_entitlement_suspended_disables():
    db = _fake_db(TenantEntitlement(module_key="timesheet", status="suspended"), None)
    assert await is_module_enabled(db, uuid.uuid4(), "timesheet") is False


@pytest.mark.asyncio
async def test_fallback_optout_missing_key_is_enabled():
    # pas d'entitlement -> fallback modules_config (opt-out : clé absente = activé)
    db = _fake_db(None, Tenant(name="T", modules_config={}))
    assert await is_module_enabled(db, uuid.uuid4(), "timesheet") is True


@pytest.mark.asyncio
async def test_fallback_explicit_false_disables():
    db = _fake_db(None, Tenant(name="T", modules_config={"timesheet": False}))
    assert await is_module_enabled(db, uuid.uuid4(), "timesheet") is False
