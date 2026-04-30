"""Tests for /api/v1/analytics/{time-to-hire,source-effectiveness}.

Phase 4.3 advanced analytics.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.api.v1.analytics_advanced import _percentile
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.offer import Offer
from app.models.position import Position


pytestmark = pytest.mark.asyncio


# ─── _percentile (pure function) ──────────────────────────────────────────────


def test_percentile_empty_returns_none():
    assert _percentile([], 50) is None


def test_percentile_single_value_returns_that_value():
    assert _percentile([42.0], 50) == 42.0
    assert _percentile([42.0], 90) == 42.0


def test_percentile_median_of_known_series():
    # [1,2,3,4,5] → median (P50) = 3
    assert _percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50) == 3.0


def test_percentile_p90_of_known_series():
    # [1..10], P90 = 9.1 (linear interp between 9 and 10 at fraction 0.1)
    assert _percentile([float(i) for i in range(1, 11)], 90) == pytest.approx(9.1)


# ─── helpers ──────────────────────────────────────────────────────────────────


async def _make_position(db, tenant_id, user_id):
    pos = Position(
        tenant_id=tenant_id, title="P", description="x",
        required_skills=[], seniority_level="mid", status="active",
        created_by=user_id,
    )
    db.add(pos)
    await db.flush()
    return pos


async def _make_application(db, tenant_id, position_id, *, created_at=None, source=None):
    cand = Candidate(
        tenant_id=tenant_id, position_id=position_id,
        name="C", email=f"c{uuid4()}@x.com", pipeline_status="new",
    )
    db.add(cand)
    await db.flush()
    app = Application(
        tenant_id=tenant_id,
        position_id=position_id,
        candidate_id=cand.id,
        source=source,
    )
    if created_at is not None:
        app.created_at = created_at
    db.add(app)
    await db.flush()
    return app


async def _make_signed_offer(db, application_id, *, signed_at, tenant_id):
    """Offers require tenant_id, enterprise_id, created_by — create the
    bare-minimum dependent rows here to keep test bodies readable."""
    from app.models.enterprise import Enterprise
    from app.models.user import User as UserModel
    # Pick any user in this tenant — the test fixture's admin is fine.
    user_row = (
        await db.execute(
            UserModel.__table__.select().where(UserModel.tenant_id == tenant_id).limit(1)
        )
    ).first()
    user_id = user_row.id if user_row else None

    ent = Enterprise(tenant_id=tenant_id, name="Test Co", created_by=user_id)
    db.add(ent)
    await db.flush()

    offer = Offer(
        application_id=application_id,
        tenant_id=tenant_id,
        enterprise_id=ent.id,
        created_by=user_id,
        status="signed",
        signed_at=signed_at,
    )
    db.add(offer)
    await db.flush()
    return offer


# ─── /time-to-hire ────────────────────────────────────────────────────────────


async def test_time_to_hire_empty_when_no_offers(client, admin_data):
    headers, _, _ = admin_data
    res = await client.get("/api/v1/analytics/time-to-hire", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["sample_size"] == 0
    assert body["median_days"] is None


async def test_time_to_hire_computes_median_and_p90(client, admin_data, db_session):
    headers, user, tenant = admin_data
    pos = await _make_position(db_session, tenant.id, user.id)

    base = datetime.now(timezone.utc) - timedelta(days=30)
    # Three signed offers with deltas 5, 10, 30 days
    for delta in (5, 10, 30):
        app = await _make_application(db_session, tenant.id, pos.id, created_at=base)
        await _make_signed_offer(db_session, app.id, tenant_id=tenant.id, signed_at=base + timedelta(days=delta))
    await db_session.commit()

    res = await client.get("/api/v1/analytics/time-to-hire", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["sample_size"] == 3
    assert body["median_days"] == pytest.approx(10, abs=0.1)
    # P90 of [5,10,30] = 5 + 0.8*(30-5) ... Actually:
    # rank = 0.9 * (3-1) = 1.8 → lo=1, hi=2, frac=0.8
    # value = 10 + 0.8*(30-10) = 26
    assert body["p90_days"] == pytest.approx(26, abs=0.1)


async def test_time_to_hire_filters_by_position(client, admin_data, db_session):
    headers, user, tenant = admin_data
    pos1 = await _make_position(db_session, tenant.id, user.id)
    pos2 = await _make_position(db_session, tenant.id, user.id)

    base = datetime.now(timezone.utc) - timedelta(days=20)
    for pos, delta in [(pos1, 5), (pos1, 10), (pos2, 50)]:
        app = await _make_application(db_session, tenant.id, pos.id, created_at=base)
        await _make_signed_offer(db_session, app.id, tenant_id=tenant.id, signed_at=base + timedelta(days=delta))
    await db_session.commit()

    res = await client.get(
        f"/api/v1/analytics/time-to-hire?position_id={pos1.id}",
        headers=headers,
    )
    body = res.json()
    assert body["sample_size"] == 2
    assert body["median_days"] == pytest.approx(7.5, abs=0.1)


async def test_time_to_hire_excludes_offers_outside_window(client, admin_data, db_session):
    headers, user, tenant = admin_data
    pos = await _make_position(db_session, tenant.id, user.id)

    # Old signed offer (1 year ago) should be excluded with default 180-day window.
    very_old = datetime.now(timezone.utc) - timedelta(days=365)
    app1 = await _make_application(db_session, tenant.id, pos.id, created_at=very_old)
    await _make_signed_offer(db_session, app1.id, tenant_id=tenant.id, signed_at=very_old + timedelta(days=10))

    # Recent offer should be included.
    recent = datetime.now(timezone.utc) - timedelta(days=10)
    app2 = await _make_application(db_session, tenant.id, pos.id, created_at=recent)
    await _make_signed_offer(db_session, app2.id, tenant_id=tenant.id, signed_at=recent + timedelta(days=3))
    await db_session.commit()

    res = await client.get("/api/v1/analytics/time-to-hire", headers=headers)
    body = res.json()
    assert body["sample_size"] == 1


# ─── /source-effectiveness ────────────────────────────────────────────────────


async def test_source_effectiveness_empty(client, admin_data):
    headers, _, _ = admin_data
    res = await client.get("/api/v1/analytics/source-effectiveness", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total_applications"] == 0
    assert body["sources"] == []


async def test_source_effectiveness_groups_by_source_and_computes_rate(
    client, admin_data, db_session
):
    headers, user, tenant = admin_data
    pos = await _make_position(db_session, tenant.id, user.id)

    # 3 referral apps, 1 signed → rate 0.33
    for _ in range(3):
        await _make_application(db_session, tenant.id, pos.id, source="referral")
    referrals = (await db_session.execute(
        Application.__table__.select().where(Application.source == "referral")
    )).all()
    await _make_signed_offer(
        db_session,
        referrals[0].id,
        tenant_id=tenant.id,
        signed_at=datetime.now(timezone.utc),
    )

    # 2 direct_apply apps, 0 signed
    for _ in range(2):
        await _make_application(db_session, tenant.id, pos.id, source="direct_apply")

    # 1 unknown-source app
    await _make_application(db_session, tenant.id, pos.id, source=None)
    await db_session.commit()

    res = await client.get("/api/v1/analytics/source-effectiveness", headers=headers)
    body = res.json()
    assert body["total_applications"] == 6

    by_source = {s["source"]: s for s in body["sources"]}
    assert by_source["referral"]["applications"] == 3
    assert by_source["referral"]["signed_offers"] == 1
    assert by_source["referral"]["signed_rate"] == pytest.approx(1 / 3, abs=0.01)
    assert by_source["direct_apply"]["applications"] == 2
    assert by_source["direct_apply"]["signed_offers"] == 0
    assert by_source["direct_apply"]["signed_rate"] == 0.0
    assert by_source["(unknown)"]["applications"] == 1


async def test_source_effectiveness_excludes_other_tenants(client, admin_data, db_session):
    headers, user, tenant = admin_data
    pos = await _make_position(db_session, tenant.id, user.id)
    await _make_application(db_session, tenant.id, pos.id, source="referral")

    # Foreign-tenant app must not appear.
    from app.models.tenant import Tenant
    from app.models.user import User as UserModel
    other = Tenant(name="Other")
    db_session.add(other)
    await db_session.flush()
    other_user = UserModel(
        tenant_id=other.id, email=f"o{uuid4()}@x.com",
        password_hash="x", full_name="X", role="admin",
    )
    db_session.add(other_user)
    await db_session.flush()
    other_pos = await _make_position(db_session, other.id, other_user.id)
    await _make_application(db_session, other.id, other_pos.id, source="referral")
    await db_session.commit()

    res = await client.get("/api/v1/analytics/source-effectiveness", headers=headers)
    body = res.json()
    assert body["total_applications"] == 1


async def test_advanced_analytics_require_auth(client):
    r1 = await client.get("/api/v1/analytics/time-to-hire")
    r2 = await client.get("/api/v1/analytics/source-effectiveness")
    assert r1.status_code in (401, 403)
    assert r2.status_code in (401, 403)
