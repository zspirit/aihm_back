"""Tests for AI Act transparency endpoints (Phase 4.1 V1_ROADMAP)."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.approval_request import ApprovalRequest
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.position import Position
from app.models.tenant import Tenant
from app.models.user import User


pytestmark = pytest.mark.asyncio


# ─── helpers ──────────────────────────────────────────────────────────────────


async def _make_candidate(db_session, tenant_id, user_id, **kwargs):
    pos = Position(
        tenant_id=tenant_id,
        title="X",
        description="x",
        required_skills=[],
        seniority_level="mid",
        status="active",
        created_by=user_id,
    )
    db_session.add(pos)
    await db_session.flush()

    cand = Candidate(
        tenant_id=tenant_id,
        position_id=pos.id,
        name="Cand X",
        email="cand@example.com",
        pipeline_status="new",
        **kwargs,
    )
    db_session.add(cand)
    await db_session.commit()
    await db_session.refresh(cand)
    return cand


# ─── GET /candidates/{id}/ai-decisions ────────────────────────────────────────


async def test_ai_decisions_empty_when_no_score_and_no_audit(client, admin_data, db_session):
    headers, user, tenant = admin_data
    cand = await _make_candidate(db_session, tenant.id, user.id)

    res = await client.get(f"/api/v1/candidates/{cand.id}/ai-decisions", headers=headers)
    assert res.status_code == 200
    assert res.json() == []


async def test_ai_decisions_includes_cv_scoring_when_score_set(client, admin_data, db_session):
    headers, user, tenant = admin_data
    cand = await _make_candidate(
        db_session, tenant.id, user.id,
        cv_score=78.0,
        cv_score_explanation={"competences": 85, "experience": 70},
    )

    res = await client.get(f"/api/v1/candidates/{cand.id}/ai-decisions", headers=headers)
    assert res.status_code == 200
    decisions = res.json()
    assert len(decisions) == 1

    d = decisions[0]
    assert d["type"] == "cv_scoring"
    assert d["model"].startswith("claude")
    assert d["confidence_score"] == pytest.approx(0.78)
    assert "78" in d["decision_summary"]
    assert d["details"] == {"competences": 85, "experience": 70}
    assert d["can_be_contested"] is True


async def test_ai_decisions_includes_audit_logs_with_actor_ai(client, admin_data, db_session):
    headers, user, tenant = admin_data
    cand = await _make_candidate(db_session, tenant.id, user.id)

    db_session.add_all([
        AuditLog(
            tenant_id=tenant.id, user_id=user.id,
            action="auto_reject",
            entity_type="candidate",
            entity_id=str(cand.id),
            details={
                "actor": "ai",
                "model": "claude-sonnet-4-6",
                "model_version": "2026-04",
                "confidence_score": 0.92,
                "summary": "Auto-rejected (score 24/100)",
            },
        ),
        # This one is a human action — must NOT appear in the AI decisions list.
        AuditLog(
            tenant_id=tenant.id, user_id=user.id,
            action="comment_added",
            entity_type="candidate",
            entity_id=str(cand.id),
            details={"actor": "user"},
        ),
    ])
    await db_session.commit()

    res = await client.get(f"/api/v1/candidates/{cand.id}/ai-decisions", headers=headers)
    assert res.status_code == 200
    decisions = res.json()
    assert len(decisions) == 1
    d = decisions[0]
    assert d["type"] == "auto_reject"
    assert d["model"] == "claude-sonnet-4-6"
    assert d["confidence_score"] == pytest.approx(0.92)
    assert d["audit_log_id"] is not None


async def test_ai_decisions_404_for_unknown_candidate(client, admin_data):
    headers, _user, _tenant = admin_data
    res = await client.get(f"/api/v1/candidates/{uuid4()}/ai-decisions", headers=headers)
    assert res.status_code == 404


async def test_ai_decisions_404_for_other_tenant_candidate(client, admin_data, db_session):
    """Cross-tenant access must 404 (not 403) — don't leak existence."""
    headers, _user, _tenant = admin_data

    # Build a candidate in a *different* tenant.
    other_tenant = Tenant(name="Other Co")
    db_session.add(other_tenant)
    await db_session.flush()
    other_user = User(
        tenant_id=other_tenant.id,
        email="other@x.com", password_hash="x", full_name="Other", role="admin",
    )
    db_session.add(other_user)
    await db_session.flush()
    foreign_cand = await _make_candidate(db_session, other_tenant.id, other_user.id)

    res = await client.get(f"/api/v1/candidates/{foreign_cand.id}/ai-decisions", headers=headers)
    assert res.status_code == 404


async def test_ai_decisions_requires_auth(client, admin_data, db_session):
    _, user, tenant = admin_data
    cand = await _make_candidate(db_session, tenant.id, user.id)
    res = await client.get(f"/api/v1/candidates/{cand.id}/ai-decisions")
    assert res.status_code in (401, 403)


# ─── POST /candidates/{id}/contest-evaluation ─────────────────────────────────


async def test_contest_evaluation_creates_pending_approval_request(
    client, admin_data, db_session
):
    headers, user, tenant = admin_data
    cand = await _make_candidate(db_session, tenant.id, user.id, cv_score=22.0)

    # The approver is a second user in the same tenant.
    approver = User(
        tenant_id=tenant.id,
        email="approver@test.com", password_hash="x", full_name="Approver",
        role="recruiter",
    )
    db_session.add(approver)
    await db_session.commit()
    await db_session.refresh(approver)

    res = await client.post(
        f"/api/v1/candidates/{cand.id}/contest-evaluation",
        headers=headers,
        json={
            "reason": "The CV mentions 8 years of Python — score is way too low.",
            "approver_id": str(approver.id),
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "pending"
    assert "approval_request_id" in body

    ar = (
        await db_session.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == body["approval_request_id"])
        )
    ).scalar_one()
    assert ar.tenant_id == tenant.id
    assert ar.requester_id == user.id
    assert ar.approver_id == approver.id
    assert ar.entity_type == "candidate"
    assert ar.entity_id == cand.id
    assert ar.status == "pending"
    assert "Contestation" in ar.title
    assert cand.name in ar.title


async def test_contest_evaluation_rejects_unknown_candidate(client, admin_data, db_session):
    headers, _user, tenant = admin_data
    approver = User(
        tenant_id=tenant.id,
        email="appr2@test.com", password_hash="x", full_name="A", role="admin",
    )
    db_session.add(approver)
    await db_session.commit()
    await db_session.refresh(approver)

    res = await client.post(
        f"/api/v1/candidates/{uuid4()}/contest-evaluation",
        headers=headers,
        json={"reason": "x" * 20, "approver_id": str(approver.id)},
    )
    assert res.status_code == 404


async def test_contest_evaluation_rejects_foreign_tenant_approver(
    client, admin_data, db_session
):
    headers, user, tenant = admin_data
    cand = await _make_candidate(db_session, tenant.id, user.id)

    # Approver in ANOTHER tenant.
    other_tenant = Tenant(name="Other 2")
    db_session.add(other_tenant)
    await db_session.flush()
    foreign_approver = User(
        tenant_id=other_tenant.id,
        email="foreign@x.com", password_hash="x", full_name="F", role="admin",
    )
    db_session.add(foreign_approver)
    await db_session.commit()
    await db_session.refresh(foreign_approver)

    res = await client.post(
        f"/api/v1/candidates/{cand.id}/contest-evaluation",
        headers=headers,
        json={
            "reason": "this is a long enough reason to pass min_length",
            "approver_id": str(foreign_approver.id),
        },
    )
    assert res.status_code == 400
    assert "approver" in res.json()["detail"].lower()


async def test_contest_evaluation_validates_reason_min_length(client, admin_data, db_session):
    headers, user, tenant = admin_data
    cand = await _make_candidate(db_session, tenant.id, user.id)

    res = await client.post(
        f"/api/v1/candidates/{cand.id}/contest-evaluation",
        headers=headers,
        json={"reason": "short", "approver_id": str(user.id)},
    )
    # Pydantic field constraint min_length=10 → 422
    assert res.status_code == 422


async def test_contest_evaluation_requires_auth(client, admin_data, db_session):
    _, user, tenant = admin_data
    cand = await _make_candidate(db_session, tenant.id, user.id)

    res = await client.post(
        f"/api/v1/candidates/{cand.id}/contest-evaluation",
        json={"reason": "x" * 20, "approver_id": str(user.id)},
    )
    assert res.status_code in (401, 403)
