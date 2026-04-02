"""Extended tests for candidate endpoints: delete, bulk-delete, update, CV download, list filters/sort."""
import uuid
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import select

from app.models.analysis import Analysis
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.consent import Consent
from app.models.interview import Interview
from app.models.match_score import MatchScore
from app.models.position import Position
from app.models.report import Report
from app.models.transcription import Transcription


# ─── Helpers ────────────────────────────────────────────────────────────────


async def _make_position(db_session, tenant_id, user_id, title="Dev Backend"):
    pos = Position(
        tenant_id=tenant_id, title=title, description="",
        required_skills=["Python"], created_by=user_id,
    )
    db_session.add(pos)
    await db_session.commit()
    await db_session.refresh(pos)
    return pos


async def _make_candidate(db_session, tenant_id, position_id=None, name="Test Candidat",
                          email="cand@test.com", pipeline_status="new", cv_score=None,
                          cv_file_path=None, viewed_at=None):
    cand = Candidate(
        tenant_id=tenant_id, position_id=position_id, name=name, email=email,
        phone="+33600000000", pipeline_status=pipeline_status, cv_score=cv_score,
        cv_file_path=cv_file_path, viewed_at=viewed_at,
    )
    db_session.add(cand)
    await db_session.commit()
    await db_session.refresh(cand)
    return cand


async def _make_interview(db_session, candidate_id, position_id, tenant_id):
    iv = Interview(candidate_id=candidate_id, position_id=position_id, tenant_id=tenant_id, status="completed")
    db_session.add(iv)
    await db_session.commit()
    await db_session.refresh(iv)
    return iv


async def _make_report(db_session, interview_id, candidate_id):
    report = Report(candidate_id=candidate_id, interview_id=interview_id, content={"summary": "Good"})
    db_session.add(report)
    await db_session.commit()
    await db_session.refresh(report)
    return report


async def _make_transcription(db_session, interview_id):
    tr = Transcription(interview_id=interview_id, full_text="Bonjour.")
    db_session.add(tr)
    await db_session.commit()
    await db_session.refresh(tr)
    return tr


async def _make_match_score(db_session, candidate_id, position_id, tenant_id, score=75.0):
    ms = MatchScore(tenant_id=tenant_id, candidate_id=candidate_id, position_id=position_id, score=score)
    db_session.add(ms)
    await db_session.commit()
    await db_session.refresh(ms)
    return ms


async def _make_application(db_session, candidate_id, position_id, tenant_id):
    app_obj = Application(tenant_id=tenant_id, candidate_id=candidate_id, position_id=position_id, pipeline_status="new")
    db_session.add(app_obj)
    await db_session.commit()
    await db_session.refresh(app_obj)
    return app_obj


@pytest.fixture()
async def setup(db_session, admin_data):
    headers, user, tenant = admin_data
    pos = await _make_position(db_session, tenant.id, user.id)
    return headers, user, tenant, pos


# ─── DELETE /candidates/{id} ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_candidate(client, db_session, setup):
    headers, user, tenant, pos = setup
    cand = await _make_candidate(db_session, tenant.id, pos.id, name="A Supprimer")
    await db_session.commit()
    res = await client.delete(f"/api/v1/candidates/{cand.id}", headers=headers)
    assert res.status_code == 204
    result = await db_session.execute(select(Candidate).where(Candidate.id == cand.id))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_candidate_with_match_scores(client, db_session, setup):
    headers, user, tenant, pos = setup
    cand = await _make_candidate(db_session, tenant.id, pos.id, name="Match Owner")
    ms = await _make_match_score(db_session, cand.id, pos.id, tenant.id)
    await db_session.commit()
    res = await client.delete(f"/api/v1/candidates/{cand.id}", headers=headers)
    assert res.status_code == 204
    result = await db_session.execute(select(MatchScore).where(MatchScore.id == ms.id))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_candidate_with_applications(client, db_session, setup):
    headers, user, tenant, pos = setup
    cand = await _make_candidate(db_session, tenant.id, pos.id, name="App Owner")
    app_obj = await _make_application(db_session, cand.id, pos.id, tenant.id)
    await db_session.commit()
    res = await client.delete(f"/api/v1/candidates/{cand.id}", headers=headers)
    assert res.status_code == 204
    result = await db_session.execute(select(Application).where(Application.id == app_obj.id))
    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_candidate_with_interviews(client, db_session, setup):
    headers, user, tenant, pos = setup
    cand = await _make_candidate(db_session, tenant.id, pos.id, name="Interview Owner")
    iv = await _make_interview(db_session, cand.id, pos.id, tenant.id)
    report = await _make_report(db_session, iv.id, cand.id)
    tr = await _make_transcription(db_session, iv.id)
    await db_session.commit()
    res = await client.delete(f"/api/v1/candidates/{cand.id}", headers=headers)
    assert res.status_code == 204
    assert (await db_session.execute(select(Interview).where(Interview.id == iv.id))).scalar_one_or_none() is None
    assert (await db_session.execute(select(Report).where(Report.id == report.id))).scalar_one_or_none() is None
    assert (await db_session.execute(select(Transcription).where(Transcription.id == tr.id))).scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_delete_candidate_not_found(client, setup):
    headers, *_ = setup
    res = await client.delete(f"/api/v1/candidates/{uuid.uuid4()}", headers=headers)
    assert res.status_code == 404
    assert "introuvable" in res.json()["detail"].lower()


# ─── POST /candidates/bulk-delete ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_delete_candidates(client, db_session, setup):
    headers, user, tenant, pos = setup
    cands = []
    for i in range(3):
        c = await _make_candidate(db_session, tenant.id, pos.id, name=f"Bulk {i}", email=f"bulk{i}@test.com")
        cands.append(c)
    await db_session.commit()
    res = await client.post("/api/v1/candidates/bulk-delete", headers=headers, json={"ids": [str(c.id) for c in cands]})
    assert res.status_code == 200
    assert res.json()["deleted"] == 3


@pytest.mark.asyncio
async def test_bulk_delete_max_limit(client, setup):
    headers, *_ = setup
    res = await client.post("/api/v1/candidates/bulk-delete", headers=headers, json={"ids": [str(uuid.uuid4()) for _ in range(101)]})
    assert res.status_code == 400
    assert "100" in res.json()["detail"]


@pytest.mark.asyncio
async def test_bulk_delete_empty_ids(client, setup):
    headers, *_ = setup
    res = await client.post("/api/v1/candidates/bulk-delete", headers=headers, json={"ids": []})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_bulk_delete_cascade_interviews(client, db_session, setup):
    headers, user, tenant, pos = setup
    cand1 = await _make_candidate(db_session, tenant.id, pos.id, name="BC1", email="bc1@test.com")
    cand2 = await _make_candidate(db_session, tenant.id, pos.id, name="BC2", email="bc2@test.com")
    iv1 = await _make_interview(db_session, cand1.id, pos.id, tenant.id)
    report1 = await _make_report(db_session, iv1.id, cand1.id)
    tr1 = await _make_transcription(db_session, iv1.id)
    ms1 = await _make_match_score(db_session, cand1.id, pos.id, tenant.id, score=80.0)
    await db_session.commit()
    res = await client.post("/api/v1/candidates/bulk-delete", headers=headers, json={"ids": [str(cand1.id), str(cand2.id)]})
    assert res.status_code == 200
    assert res.json()["deleted"] == 2
    assert (await db_session.execute(select(Interview).where(Interview.id == iv1.id))).scalar_one_or_none() is None
    assert (await db_session.execute(select(MatchScore).where(MatchScore.id == ms1.id))).scalar_one_or_none() is None


# ─── PUT /candidates/{id} ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_candidate(client, db_session, setup):
    headers, user, tenant, pos = setup
    cand = await _make_candidate(db_session, tenant.id, pos.id, name="Original", email="orig@test.com")
    await db_session.commit()
    res = await client.put(f"/api/v1/candidates/{cand.id}", headers=headers,
                           json={"name": "Updated", "email": "up@test.com", "phone": "+33699999999"})
    assert res.status_code == 200
    assert res.json()["name"] == "Updated"


@pytest.mark.asyncio
async def test_update_tags_and_notes(client, db_session, setup):
    headers, user, tenant, pos = setup
    cand = await _make_candidate(db_session, tenant.id, pos.id, name="Tags", email="tags@test.com")
    await db_session.commit()
    tags = ["senior", "python"]
    notes = "Candidat prometteur."
    res = await client.put(f"/api/v1/candidates/{cand.id}", headers=headers, json={"tags": tags, "notes": notes})
    assert res.status_code == 200
    assert res.json()["tags"] == tags
    assert res.json()["notes"] == notes


@pytest.mark.asyncio
async def test_update_candidate_not_found(client, setup):
    headers, *_ = setup
    res = await client.put(f"/api/v1/candidates/{uuid.uuid4()}", headers=headers, json={"name": "Ghost"})
    assert res.status_code == 404


# ─── GET /candidates — list with sort/filter ────────────────────────────────


@pytest.mark.asyncio
async def test_list_candidates_sort_by_name(client, db_session, setup):
    headers, user, tenant, pos = setup
    for name in ["Zara", "Alice", "Mohamed"]:
        await _make_candidate(db_session, tenant.id, pos.id, name=name, email=f"{name.lower()}@t.com")
    await db_session.commit()
    res = await client.get("/api/v1/candidates", headers=headers, params={"sort_by": "name", "sort_order": "asc"})
    assert res.status_code == 200
    names = [i["name"] for i in res.json()["items"]]
    assert names == sorted(names)


@pytest.mark.asyncio
async def test_list_candidates_sort_by_score(client, db_session, setup):
    headers, user, tenant, pos = setup
    for i, score in enumerate([30.0, 85.0, 60.0]):
        await _make_candidate(db_session, tenant.id, pos.id, name=f"S{i}", email=f"s{i}@t.com", cv_score=score)
    await db_session.commit()
    res = await client.get("/api/v1/candidates", headers=headers, params={"sort_by": "cv_score", "sort_order": "desc"})
    assert res.status_code == 200
    scores = [i["cv_score"] for i in res.json()["items"] if i["cv_score"] is not None]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_list_candidates_filter_status(client, db_session, setup):
    headers, user, tenant, pos = setup
    await _make_candidate(db_session, tenant.id, pos.id, name="Ana1", email="a1@t.com", pipeline_status="cv_analyzed")
    await _make_candidate(db_session, tenant.id, pos.id, name="Ana2", email="a2@t.com", pipeline_status="cv_analyzed")
    await _make_candidate(db_session, tenant.id, pos.id, name="New1", email="n1@t.com", pipeline_status="new")
    await db_session.commit()
    res = await client.get("/api/v1/candidates", headers=headers, params={"status_filter": "cv_analyzed"})
    assert res.status_code == 200
    assert res.json()["total"] == 2


@pytest.mark.asyncio
async def test_list_candidates_filter_position(client, db_session, setup):
    headers, user, tenant, pos = setup
    pos2 = await _make_position(db_session, tenant.id, user.id, title="Frontend")
    await db_session.commit()
    await _make_candidate(db_session, tenant.id, pos.id, name="Back", email="back@t.com")
    await _make_candidate(db_session, tenant.id, pos2.id, name="Front", email="front@t.com")
    await db_session.commit()
    res = await client.get("/api/v1/candidates", headers=headers, params={"position_id": str(pos.id)})
    assert res.status_code == 200
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["name"] == "Back"


@pytest.mark.asyncio
async def test_list_candidates_search(client, db_session, setup):
    headers, user, tenant, pos = setup
    await _make_candidate(db_session, tenant.id, pos.id, name="Ahmed Benali", email="ahmed@t.com")
    await _make_candidate(db_session, tenant.id, pos.id, name="Leila Tazi", email="leila@t.com")
    await db_session.commit()
    res = await client.get("/api/v1/candidates", headers=headers, params={"search": "Benali"})
    assert res.status_code == 200
    assert res.json()["total"] == 1


@pytest.mark.asyncio
async def test_list_candidates_unread(client, db_session, setup):
    from datetime import datetime, timezone
    headers, user, tenant, pos = setup
    await _make_candidate(db_session, tenant.id, pos.id, name="Unread", email="unread@t.com", viewed_at=None)
    await _make_candidate(db_session, tenant.id, pos.id, name="Read", email="read@t.com", viewed_at=datetime.now(timezone.utc))
    await db_session.commit()
    res = await client.get("/api/v1/candidates", headers=headers, params={"unread": True})
    assert res.status_code == 200
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["name"] == "Unread"


@pytest.mark.asyncio
async def test_list_candidates_pagination(client, db_session, setup):
    headers, user, tenant, pos = setup
    for i in range(5):
        await _make_candidate(db_session, tenant.id, pos.id, name=f"P{i}", email=f"p{i}@t.com")
    await db_session.commit()
    res = await client.get("/api/v1/candidates", headers=headers, params={"page": 1, "page_size": 2})
    assert res.status_code == 200
    assert res.json()["total"] == 5
    assert len(res.json()["items"]) == 2


# ─── GET /candidates/{id} — viewed_at ───────────────────────────────────────


@pytest.mark.asyncio
async def test_candidate_viewed_at(client, db_session, setup):
    headers, user, tenant, pos = setup
    cand = await _make_candidate(db_session, tenant.id, pos.id, name="Unseen", email="unseen@t.com")
    await db_session.commit()
    res = await client.get(f"/api/v1/candidates/{cand.id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["viewed_at"] is not None
    first_viewed = res.json()["viewed_at"]
    res2 = await client.get(f"/api/v1/candidates/{cand.id}", headers=headers)
    assert res2.json()["viewed_at"] == first_viewed


# ─── CV Download ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_download_cv(client, db_session, setup):
    headers, user, tenant, pos = setup
    cand = await _make_candidate(db_session, tenant.id, pos.id, name="CV Owner", email="cv@t.com", cv_file_path="cvs/fake.pdf")
    await db_session.commit()
    fake_bytes = b"%PDF-1.4 fake"
    with patch("app.services.storage.download_file", return_value=fake_bytes):
        res = await client.get(f"/api/v1/candidates/{cand.id}/cv/download", headers=headers)
    assert res.status_code == 200
    assert "attachment" in res.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_download_cv_no_file(client, db_session, setup):
    headers, user, tenant, pos = setup
    cand = await _make_candidate(db_session, tenant.id, pos.id, name="No CV", email="nocv@t.com", cv_file_path=None)
    await db_session.commit()
    res = await client.get(f"/api/v1/candidates/{cand.id}/cv/download", headers=headers)
    assert res.status_code == 404


# ─── Tenant isolation ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_candidate_tenant_isolation(client, db_session, setup):
    headers, user, tenant, pos = setup
    from app.models.tenant import Tenant
    from app.models.user import User
    from app.core.security import hash_password
    other_tenant = Tenant(name="Other Corp")
    db_session.add(other_tenant)
    await db_session.commit()
    await db_session.refresh(other_tenant)
    other_user = User(tenant_id=other_tenant.id, email="other@other.com", password_hash=hash_password("pass"), full_name="Other", role="admin")
    db_session.add(other_user)
    await db_session.commit()
    await db_session.refresh(other_user)
    other_pos = await _make_position(db_session, other_tenant.id, other_user.id)
    other_cand = await _make_candidate(db_session, other_tenant.id, other_pos.id, name="Other", email="oc@other.com")
    res = await client.delete(f"/api/v1/candidates/{other_cand.id}", headers=headers)
    assert res.status_code == 404
    result = await db_session.execute(select(Candidate).where(Candidate.id == other_cand.id))
    assert result.scalar_one_or_none() is not None
