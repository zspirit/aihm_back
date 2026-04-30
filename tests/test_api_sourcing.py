"""Tests for /api/v1/positions/{id}/sourcing-candidates (Phase 4.4)."""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.models.candidate import Candidate
from app.models.position import Position


pytestmark = pytest.mark.asyncio


async def _make_position(db, tenant_id, user_id, *, required_skills):
    pos = Position(
        tenant_id=tenant_id, title="P", description="x",
        required_skills=required_skills,
        seniority_level="mid", status="active",
        created_by=user_id,
    )
    db.add(pos)
    await db.flush()
    return pos


async def _make_candidate(db, tenant_id, *, name, skills, cv_score=None,
                          pipeline_status="new", position_id=None):
    cand = Candidate(
        tenant_id=tenant_id,
        position_id=position_id,
        name=name,
        email=f"{name.replace(' ', '.').lower()}@x.com",
        cv_parsed_data={"skills": skills} if skills is not None else None,
        cv_score=cv_score,
        pipeline_status=pipeline_status,
    )
    db.add(cand)
    await db.flush()
    return cand


# ─── Empty cases ──────────────────────────────────────────────────────────────


async def test_sourcing_404_for_unknown_position(client, admin_data):
    headers, _, _ = admin_data
    res = await client.get(
        f"/api/v1/positions/{uuid4()}/sourcing-candidates", headers=headers,
    )
    assert res.status_code == 404


async def test_sourcing_returns_empty_when_position_has_no_required_skills(
    client, admin_data, db_session,
):
    headers, user, tenant = admin_data
    pos = await _make_position(db_session, tenant.id, user.id, required_skills=[])
    await db_session.commit()

    res = await client.get(
        f"/api/v1/positions/{pos.id}/sourcing-candidates", headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["required_skills_count"] == 0
    assert body["suggestions"] == []


async def test_sourcing_skips_candidates_without_cv_parsed_data(
    client, admin_data, db_session,
):
    headers, user, tenant = admin_data
    pos = await _make_position(
        db_session, tenant.id, user.id, required_skills=["Python", "FastAPI"],
    )
    # Candidate with no cv_parsed_data → unscorable, must be skipped.
    await _make_candidate(db_session, tenant.id, name="No CV", skills=None)
    await db_session.commit()

    res = await client.get(
        f"/api/v1/positions/{pos.id}/sourcing-candidates", headers=headers,
    )
    assert res.json()["suggestions"] == []


# ─── Scoring + ranking ────────────────────────────────────────────────────────


async def test_sourcing_ranks_by_overlap_then_cv_score(
    client, admin_data, db_session,
):
    headers, user, tenant = admin_data
    pos = await _make_position(
        db_session, tenant.id, user.id,
        required_skills=["Python", "FastAPI", "PostgreSQL"],
    )
    # 3 of 3 required skills, low cv_score
    await _make_candidate(
        db_session, tenant.id, name="Best",
        skills=["Python", "FastAPI", "PostgreSQL"], cv_score=50.0,
    )
    # 2 of 3 required, but the highest cv_score
    await _make_candidate(
        db_session, tenant.id, name="Mid CV-king",
        skills=["Python", "FastAPI"], cv_score=95.0,
    )
    # 1 of 3 required → at threshold (33%)
    await _make_candidate(
        db_session, tenant.id, name="Low",
        skills=["Python", "Other"], cv_score=80.0,
    )
    # No matching skill at all → must be filtered out
    await _make_candidate(
        db_session, tenant.id, name="None",
        skills=["Java", "Spring"], cv_score=99.0,
    )
    await db_session.commit()

    res = await client.get(
        f"/api/v1/positions/{pos.id}/sourcing-candidates?min_overlap=33",
        headers=headers,
    )
    body = res.json()
    names = [s["name"] for s in body["suggestions"]]
    # Best (100%) > Mid CV-king (66%) > Low (33%); 'None' excluded.
    assert names == ["Best", "Mid CV-king", "Low"]
    assert body["suggestions"][0]["overlap_score"] == 100
    assert body["suggestions"][1]["overlap_score"] == 67
    assert body["suggestions"][2]["overlap_score"] == 33


async def test_sourcing_min_overlap_filters_out_low_scores(
    client, admin_data, db_session,
):
    headers, user, tenant = admin_data
    pos = await _make_position(
        db_session, tenant.id, user.id,
        required_skills=["Python", "FastAPI", "PostgreSQL"],
    )
    await _make_candidate(
        db_session, tenant.id, name="Has 1 of 3",
        skills=["Python", "Java"],
    )
    await db_session.commit()

    # min_overlap=50 → 33% candidate excluded.
    res = await client.get(
        f"/api/v1/positions/{pos.id}/sourcing-candidates?min_overlap=50",
        headers=headers,
    )
    assert res.json()["suggestions"] == []


async def test_sourcing_substring_matches(client, admin_data, db_session):
    """'Python' in required matches 'Python 3.12' on the candidate."""
    headers, user, tenant = admin_data
    pos = await _make_position(
        db_session, tenant.id, user.id,
        required_skills=["Python"],
    )
    await _make_candidate(
        db_session, tenant.id, name="Subst",
        skills=["Python 3.12 (advanced)"],
    )
    await db_session.commit()

    res = await client.get(
        f"/api/v1/positions/{pos.id}/sourcing-candidates", headers=headers,
    )
    suggestions = res.json()["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["overlap_score"] == 100


async def test_sourcing_excludes_candidates_already_applied_to_this_position(
    client, admin_data, db_session,
):
    headers, user, tenant = admin_data
    pos = await _make_position(
        db_session, tenant.id, user.id, required_skills=["Python"],
    )
    # Already applied to this exact position.
    await _make_candidate(
        db_session, tenant.id, name="Already in",
        skills=["Python"], position_id=pos.id,
    )
    # Free agent.
    await _make_candidate(
        db_session, tenant.id, name="Free agent",
        skills=["Python"],
    )
    await db_session.commit()

    res = await client.get(
        f"/api/v1/positions/{pos.id}/sourcing-candidates", headers=headers,
    )
    names = [s["name"] for s in res.json()["suggestions"]]
    assert names == ["Free agent"]


async def test_sourcing_can_include_already_applied_with_flag(
    client, admin_data, db_session,
):
    headers, user, tenant = admin_data
    pos = await _make_position(
        db_session, tenant.id, user.id, required_skills=["Python"],
    )
    await _make_candidate(
        db_session, tenant.id, name="Already in",
        skills=["Python"], position_id=pos.id,
    )
    await db_session.commit()

    res = await client.get(
        f"/api/v1/positions/{pos.id}/sourcing-candidates"
        f"?exclude_already_applied=false",
        headers=headers,
    )
    names = [s["name"] for s in res.json()["suggestions"]]
    assert names == ["Already in"]


async def test_sourcing_respects_limit(client, admin_data, db_session):
    headers, user, tenant = admin_data
    pos = await _make_position(
        db_session, tenant.id, user.id, required_skills=["Python"],
    )
    for i in range(5):
        await _make_candidate(
            db_session, tenant.id, name=f"C{i}", skills=["Python"], cv_score=i,
        )
    await db_session.commit()

    res = await client.get(
        f"/api/v1/positions/{pos.id}/sourcing-candidates?limit=3",
        headers=headers,
    )
    assert len(res.json()["suggestions"]) == 3


async def test_sourcing_isolates_tenants(client, admin_data, db_session):
    """Foreign-tenant candidates must never appear."""
    headers, user, tenant = admin_data
    pos = await _make_position(
        db_session, tenant.id, user.id, required_skills=["Python"],
    )

    # Candidate in another tenant.
    from app.models.tenant import Tenant
    other_t = Tenant(name="Other")
    db_session.add(other_t)
    await db_session.flush()
    await _make_candidate(other_t and db_session, other_t.id, name="Foreign", skills=["Python"])
    await db_session.commit()

    res = await client.get(
        f"/api/v1/positions/{pos.id}/sourcing-candidates", headers=headers,
    )
    names = [s["name"] for s in res.json()["suggestions"]]
    assert "Foreign" not in names


async def test_sourcing_requires_auth(client, admin_data, db_session):
    _, user, tenant = admin_data
    pos = await _make_position(
        db_session, tenant.id, user.id, required_skills=["Python"],
    )
    await db_session.commit()
    res = await client.get(f"/api/v1/positions/{pos.id}/sourcing-candidates")
    assert res.status_code in (401, 403)
