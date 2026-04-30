"""Tests for /api/v1/interviews/{id}/psychometrics endpoints (Phase 4.1)."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.position import Position
from app.models.psychometric import PsychometricAssessment
from app.models.tenant import Tenant
from app.models.user import User


pytestmark = pytest.mark.asyncio


def _full_payload(**overrides):
    body = {
        "score_communication": 4,
        "score_problem_solving": 5,
        "score_team_fit": 3,
        "score_stress_handling": 4,
        "score_leadership": 3,
    }
    body.update(overrides)
    return body


async def _make_interview(db, tenant_id, user_id):
    pos = Position(
        tenant_id=tenant_id, title="P", description="x",
        required_skills=[], seniority_level="mid", status="active",
        created_by=user_id,
    )
    db.add(pos)
    await db.flush()
    cand = Candidate(
        tenant_id=tenant_id, position_id=pos.id,
        name="C", email=f"c{uuid4()}@x.com", pipeline_status="evaluated",
    )
    db.add(cand)
    await db.flush()
    iv = Interview(
        tenant_id=tenant_id,
        candidate_id=cand.id,
        position_id=pos.id,
        status="completed",
    )
    db.add(iv)
    await db.flush()
    return iv


# ─── POST ─────────────────────────────────────────────────────────────────────


async def test_submit_returns_202_and_persists_scores(client, admin_data, db_session):
    headers, user, tenant = admin_data
    iv = await _make_interview(db_session, tenant.id, user.id)
    await db_session.commit()

    res = await client.post(
        f"/api/v1/interviews/{iv.id}/psychometrics",
        headers=headers,
        json=_full_payload(score_communication=5, score_leadership=4),
    )
    assert res.status_code == 202
    body = res.json()
    assert body["score_communication"] == 5
    assert body["score_leadership"] == 4
    assert body["interview_id"] == str(iv.id)
    assert body["submitted_by"] == str(user.id)
    # Async LLM analysis hasn't run yet.
    assert body["traits_json"] is None
    assert body["turnover_risk"] is None
    assert body["analyzed_at"] is None


@pytest.mark.parametrize("field", [
    "score_communication",
    "score_problem_solving",
    "score_team_fit",
    "score_stress_handling",
    "score_leadership",
])
async def test_submit_rejects_score_below_1(client, admin_data, db_session, field):
    headers, user, tenant = admin_data
    iv = await _make_interview(db_session, tenant.id, user.id)
    await db_session.commit()

    res = await client.post(
        f"/api/v1/interviews/{iv.id}/psychometrics",
        headers=headers,
        json=_full_payload(**{field: 0}),
    )
    assert res.status_code == 422


async def test_submit_rejects_score_above_5(client, admin_data, db_session):
    headers, user, tenant = admin_data
    iv = await _make_interview(db_session, tenant.id, user.id)
    await db_session.commit()

    res = await client.post(
        f"/api/v1/interviews/{iv.id}/psychometrics",
        headers=headers,
        json=_full_payload(score_communication=6),
    )
    assert res.status_code == 422


async def test_submit_404_for_unknown_interview(client, admin_data):
    headers, _, _ = admin_data
    res = await client.post(
        f"/api/v1/interviews/{uuid4()}/psychometrics",
        headers=headers,
        json=_full_payload(),
    )
    assert res.status_code == 404


async def test_submit_404_for_other_tenant_interview(client, admin_data, db_session):
    headers, _user, _tenant = admin_data

    other_tenant = Tenant(name="Other Co")
    db_session.add(other_tenant)
    await db_session.flush()
    other_user = User(
        tenant_id=other_tenant.id, email=f"o{uuid4()}@x.com",
        password_hash="x", full_name="X", role="admin",
    )
    db_session.add(other_user)
    await db_session.flush()
    foreign_iv = await _make_interview(db_session, other_tenant.id, other_user.id)
    await db_session.commit()

    res = await client.post(
        f"/api/v1/interviews/{foreign_iv.id}/psychometrics",
        headers=headers,
        json=_full_payload(),
    )
    assert res.status_code == 404


async def test_submit_409_when_already_exists(client, admin_data, db_session):
    headers, user, tenant = admin_data
    iv = await _make_interview(db_session, tenant.id, user.id)
    await db_session.commit()

    first = await client.post(
        f"/api/v1/interviews/{iv.id}/psychometrics",
        headers=headers, json=_full_payload(),
    )
    assert first.status_code == 202

    second = await client.post(
        f"/api/v1/interviews/{iv.id}/psychometrics",
        headers=headers, json=_full_payload(score_communication=2),
    )
    assert second.status_code == 409


async def test_submit_requires_auth(client, admin_data, db_session):
    _, user, tenant = admin_data
    iv = await _make_interview(db_session, tenant.id, user.id)
    await db_session.commit()

    res = await client.post(
        f"/api/v1/interviews/{iv.id}/psychometrics",
        json=_full_payload(),
    )
    assert res.status_code in (401, 403)


# ─── GET ──────────────────────────────────────────────────────────────────────


async def test_get_returns_assessment(client, admin_data, db_session):
    headers, user, tenant = admin_data
    iv = await _make_interview(db_session, tenant.id, user.id)
    await db_session.commit()

    await client.post(
        f"/api/v1/interviews/{iv.id}/psychometrics",
        headers=headers, json=_full_payload(),
    )
    res = await client.get(
        f"/api/v1/interviews/{iv.id}/psychometrics", headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["score_communication"] == 4


async def test_get_404_when_no_assessment(client, admin_data, db_session):
    headers, user, tenant = admin_data
    iv = await _make_interview(db_session, tenant.id, user.id)
    await db_session.commit()

    res = await client.get(
        f"/api/v1/interviews/{iv.id}/psychometrics", headers=headers,
    )
    assert res.status_code == 404
    assert "no assessment" in res.json()["detail"].lower()


async def test_get_returns_filled_traits_when_analysis_done(client, admin_data, db_session):
    """Once the LLM follow-up has run and populated traits_json + turnover_risk,
    GET reflects that."""
    headers, user, tenant = admin_data
    iv = await _make_interview(db_session, tenant.id, user.id)
    db_session.add(PsychometricAssessment(
        tenant_id=tenant.id,
        interview_id=iv.id,
        candidate_id=iv.candidate_id,
        submitted_by=user.id,
        score_communication=5, score_problem_solving=5,
        score_team_fit=5, score_stress_handling=5, score_leadership=5,
        traits_json={"empathy": 0.8, "drive": 0.9},
        turnover_risk="low",
        analyzed_at=datetime.now(timezone.utc),
    ))
    await db_session.commit()

    res = await client.get(
        f"/api/v1/interviews/{iv.id}/psychometrics", headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["traits_json"] == {"empathy": 0.8, "drive": 0.9}
    assert body["turnover_risk"] == "low"
    assert body["analyzed_at"] is not None
