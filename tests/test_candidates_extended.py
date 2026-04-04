"""Extended tests for candidate endpoints: delete, bulk-delete, update, CV download, list filters/sort."""
import uuid
from unittest.mock import patch, MagicMock

import pytest
import pytest_asyncio

from app.models.analysis import Analysis
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.consent import Consent
from app.models.interview import Interview
from app.models.match_score import MatchScore
from app.models.position import Position
from app.models.report import Report
from app.models.transcription import Transcription

from tests.conftest import _create_user, TestSession


# ─── Helpers ────────────────────────────────────────────────────────────────


async def _make_position(session, tenant_id, user_id, title="Dev Backend"):
    pos = Position(
        tenant_id=tenant_id, title=title, description="",
        required_skills=["Python"], created_by=user_id,
    )
    session.add(pos)
    await session.flush()
    return pos


async def _make_candidate(session, tenant_id, position_id=None, name="Test Candidat",
                          email="cand@test.com", pipeline_status="new", cv_score=None,
                          cv_file_path=None, viewed_at=None):
    cand = Candidate(
        tenant_id=tenant_id, position_id=position_id, name=name, email=email,
        phone="+33600000000", pipeline_status=pipeline_status, cv_score=cv_score,
        cv_file_path=cv_file_path, viewed_at=viewed_at,
    )
    session.add(cand)
    await session.flush()
    return cand


async def _make_interview(session, candidate_id, position_id, tenant_id):
    iv = Interview(candidate_id=candidate_id, position_id=position_id, tenant_id=tenant_id, status="completed")
    session.add(iv)
    await session.flush()
    return iv


async def _make_report(session, interview_id, candidate_id):
    report = Report(candidate_id=candidate_id, interview_id=interview_id, content={"summary": "Good"})
    session.add(report)
    await session.flush()
    return report


async def _make_transcription(session, interview_id):
    tr = Transcription(interview_id=interview_id, full_text="Bonjour.")
    session.add(tr)
    await session.flush()
    return tr


async def _make_match_score(session, candidate_id, position_id, tenant_id, score=75.0):
    ms = MatchScore(tenant_id=tenant_id, candidate_id=candidate_id, position_id=position_id, score=score)
    session.add(ms)
    await session.flush()
    return ms


async def _make_application(session, candidate_id, position_id, tenant_id):
    app_obj = Application(tenant_id=tenant_id, candidate_id=candidate_id, position_id=position_id, pipeline_status="new")
    session.add(app_obj)
    await session.flush()
    return app_obj


@pytest_asyncio.fixture()
async def setup(_setup_db):
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "admin@test.com", "admin")
        pos = await _make_position(session, tenant.id, user.id)
        await session.commit()
        user_id = user.id
        tenant_id = tenant.id
        pos_id = pos.id
    return headers, user_id, tenant_id, pos_id


# ─── DELETE /candidates/{id} ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_candidate(client, setup):
    headers, user_id, tenant_id, pos_id = setup
    async with TestSession() as session:
        cand = await _make_candidate(session, tenant_id, pos_id, name="A Supprimer")
        await session.commit()
        cand_id = cand.id
    res = await client.delete(f"/api/v1/candidates/{cand_id}", headers=headers)
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_delete_candidate_with_match_scores(client, setup):
    headers, user_id, tenant_id, pos_id = setup
    async with TestSession() as session:
        cand = await _make_candidate(session, tenant_id, pos_id, name="Match Owner")
        ms = await _make_match_score(session, cand.id, pos_id, tenant_id)
        await session.commit()
        cand_id = cand.id
    res = await client.delete(f"/api/v1/candidates/{cand_id}", headers=headers)
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_delete_candidate_with_applications(client, setup):
    headers, user_id, tenant_id, pos_id = setup
    async with TestSession() as session:
        cand = await _make_candidate(session, tenant_id, pos_id, name="App Owner")
        app_obj = await _make_application(session, cand.id, pos_id, tenant_id)
        await session.commit()
        cand_id = cand.id
    res = await client.delete(f"/api/v1/candidates/{cand_id}", headers=headers)
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_delete_candidate_with_interviews(client, setup):
    headers, user_id, tenant_id, pos_id = setup
    async with TestSession() as session:
        cand = await _make_candidate(session, tenant_id, pos_id, name="Interview Owner")
        iv = await _make_interview(session, cand.id, pos_id, tenant_id)
        report = await _make_report(session, iv.id, cand.id)
        tr = await _make_transcription(session, iv.id)
        await session.commit()
        cand_id = cand.id
    res = await client.delete(f"/api/v1/candidates/{cand_id}", headers=headers)
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_delete_candidate_not_found(client, setup):
    headers, *_ = setup
    res = await client.delete(f"/api/v1/candidates/{uuid.uuid4()}", headers=headers)
    assert res.status_code == 404
    assert "introuvable" in res.json()["detail"].lower()


# ─── POST /candidates/bulk-delete ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_delete_candidates(client, setup):
    headers, user_id, tenant_id, pos_id = setup
    async with TestSession() as session:
        cands = []
        for i in range(3):
            c = await _make_candidate(session, tenant_id, pos_id, name=f"Bulk {i}", email=f"bulk{i}@test.com")
            cands.append(c)
        await session.commit()
        cand_ids = [str(c.id) for c in cands]
    res = await client.post("/api/v1/candidates/bulk-delete", headers=headers, json={"ids": cand_ids})
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
async def test_bulk_delete_cascade_interviews(client, setup):
    headers, user_id, tenant_id, pos_id = setup
    async with TestSession() as session:
        cand1 = await _make_candidate(session, tenant_id, pos_id, name="BC1", email="bc1@test.com")
        cand2 = await _make_candidate(session, tenant_id, pos_id, name="BC2", email="bc2@test.com")
        iv1 = await _make_interview(session, cand1.id, pos_id, tenant_id)
        report1 = await _make_report(session, iv1.id, cand1.id)
        tr1 = await _make_transcription(session, iv1.id)
        ms1 = await _make_match_score(session, cand1.id, pos_id, tenant_id, score=80.0)
        await session.commit()
        cand1_id = str(cand1.id)
        cand2_id = str(cand2.id)
    res = await client.post("/api/v1/candidates/bulk-delete", headers=headers, json={"ids": [cand1_id, cand2_id]})
    assert res.status_code == 200
    assert res.json()["deleted"] == 2


# ─── PUT /candidates/{id} ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_candidate(client, setup):
    headers, user_id, tenant_id, pos_id = setup
    async with TestSession() as session:
        cand = await _make_candidate(session, tenant_id, pos_id, name="Original", email="orig@test.com")
        await session.commit()
        cand_id = cand.id
    res = await client.put(f"/api/v1/candidates/{cand_id}", headers=headers,
                           json={"name": "Updated", "email": "up@test.com", "phone": "+33699999999"})
    assert res.status_code == 200
    assert res.json()["name"] == "Updated"


@pytest.mark.asyncio
async def test_update_tags_and_notes(client, setup):
    headers, user_id, tenant_id, pos_id = setup
    async with TestSession() as session:
        cand = await _make_candidate(session, tenant_id, pos_id, name="Tags", email="tags@test.com")
        await session.commit()
        cand_id = cand.id
    tags = ["senior", "python"]
    notes = "Candidat prometteur."
    res = await client.put(f"/api/v1/candidates/{cand_id}", headers=headers, json={"tags": tags, "notes": notes})
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
async def test_list_candidates_sort_by_name(client, setup):
    headers, user_id, tenant_id, pos_id = setup
    async with TestSession() as session:
        for name in ["Zara", "Alice", "Mohamed"]:
            await _make_candidate(session, tenant_id, pos_id, name=name, email=f"{name.lower()}@t.com")
        await session.commit()
    res = await client.get("/api/v1/candidates", headers=headers, params={"sort_by": "name", "sort_order": "asc"})
    assert res.status_code == 200
    names = [i["name"] for i in res.json()["items"]]
    assert names == sorted(names)


@pytest.mark.asyncio
async def test_list_candidates_sort_by_score(client, setup):
    headers, user_id, tenant_id, pos_id = setup
    async with TestSession() as session:
        for i, score in enumerate([30.0, 85.0, 60.0]):
            await _make_candidate(session, tenant_id, pos_id, name=f"S{i}", email=f"s{i}@t.com", cv_score=score)
        await session.commit()
    res = await client.get("/api/v1/candidates", headers=headers, params={"sort_by": "cv_score", "sort_order": "desc"})
    assert res.status_code == 200
    scores = [i["cv_score"] for i in res.json()["items"] if i["cv_score"] is not None]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_list_candidates_filter_status(client, setup):
    headers, user_id, tenant_id, pos_id = setup
    async with TestSession() as session:
        await _make_candidate(session, tenant_id, pos_id, name="Ana1", email="a1@t.com", pipeline_status="cv_analyzed")
        await _make_candidate(session, tenant_id, pos_id, name="Ana2", email="a2@t.com", pipeline_status="cv_analyzed")
        await _make_candidate(session, tenant_id, pos_id, name="New1", email="n1@t.com", pipeline_status="new")
        await session.commit()
    res = await client.get("/api/v1/candidates", headers=headers, params={"status_filter": "cv_analyzed"})
    assert res.status_code == 200
    assert res.json()["total"] == 2


@pytest.mark.asyncio
async def test_list_candidates_filter_position(client, setup):
    headers, user_id, tenant_id, pos_id = setup
    async with TestSession() as session:
        pos2 = await _make_position(session, tenant_id, user_id, title="Frontend")
        await _make_candidate(session, tenant_id, pos_id, name="Back", email="back@t.com")
        await _make_candidate(session, tenant_id, pos2.id, name="Front", email="front@t.com")
        await session.commit()
    res = await client.get("/api/v1/candidates", headers=headers, params={"position_id": str(pos_id)})
    assert res.status_code == 200
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["name"] == "Back"


@pytest.mark.asyncio
async def test_list_candidates_search(client, setup):
    headers, user_id, tenant_id, pos_id = setup
    async with TestSession() as session:
        await _make_candidate(session, tenant_id, pos_id, name="Ahmed Benali", email="ahmed@t.com")
        await _make_candidate(session, tenant_id, pos_id, name="Leila Tazi", email="leila@t.com")
        await session.commit()
    res = await client.get("/api/v1/candidates", headers=headers, params={"search": "Benali"})
    assert res.status_code == 200
    assert res.json()["total"] == 1


@pytest.mark.asyncio
async def test_list_candidates_unread(client, setup):
    from datetime import datetime, timezone
    headers, user_id, tenant_id, pos_id = setup
    async with TestSession() as session:
        await _make_candidate(session, tenant_id, pos_id, name="Unread", email="unread@t.com", viewed_at=None)
        await _make_candidate(session, tenant_id, pos_id, name="Read", email="read@t.com", viewed_at=datetime.now(timezone.utc))
        await session.commit()
    res = await client.get("/api/v1/candidates", headers=headers, params={"unread": True})
    assert res.status_code == 200
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["name"] == "Unread"


@pytest.mark.asyncio
async def test_list_candidates_pagination(client, setup):
    headers, user_id, tenant_id, pos_id = setup
    async with TestSession() as session:
        for i in range(5):
            await _make_candidate(session, tenant_id, pos_id, name=f"P{i}", email=f"p{i}@t.com")
        await session.commit()
    res = await client.get("/api/v1/candidates", headers=headers, params={"page": 1, "page_size": 2})
    assert res.status_code == 200
    assert res.json()["total"] == 5
    assert len(res.json()["items"]) == 2


# ─── GET /candidates/{id} — viewed_at ───────────────────────────────────────


@pytest.mark.asyncio
async def test_candidate_viewed_at(client, setup):
    headers, user_id, tenant_id, pos_id = setup
    async with TestSession() as session:
        cand = await _make_candidate(session, tenant_id, pos_id, name="Unseen", email="unseen@t.com")
        await session.commit()
        cand_id = cand.id
    res = await client.get(f"/api/v1/candidates/{cand_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["viewed_at"] is not None
    first_viewed = res.json()["viewed_at"]
    res2 = await client.get(f"/api/v1/candidates/{cand_id}", headers=headers)
    assert res2.json()["viewed_at"] == first_viewed


# ─── CV Download ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_download_cv(client, setup):
    headers, user_id, tenant_id, pos_id = setup
    async with TestSession() as session:
        cand = await _make_candidate(session, tenant_id, pos_id, name="CV Owner", email="cv@t.com", cv_file_path="cvs/fake.pdf")
        await session.commit()
        cand_id = cand.id
    fake_bytes = b"%PDF-1.4 fake"
    with patch("app.services.storage.download_file", return_value=fake_bytes):
        res = await client.get(f"/api/v1/candidates/{cand_id}/cv/download", headers=headers)
    assert res.status_code == 200
    assert "attachment" in res.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_download_cv_no_file(client, setup):
    headers, user_id, tenant_id, pos_id = setup
    async with TestSession() as session:
        cand = await _make_candidate(session, tenant_id, pos_id, name="No CV", email="nocv@t.com", cv_file_path=None)
        await session.commit()
        cand_id = cand.id
    res = await client.get(f"/api/v1/candidates/{cand_id}/cv/download", headers=headers)
    assert res.status_code == 404


# ─── Tenant isolation ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_candidate_tenant_isolation(client, setup):
    headers, user_id, tenant_id, pos_id = setup
    from app.models.tenant import Tenant
    from app.models.user import User
    from app.core.security import hash_password
    async with TestSession() as session:
        other_tenant = Tenant(name="Other Corp")
        session.add(other_tenant)
        await session.flush()
        other_user = User(tenant_id=other_tenant.id, email="other@other.com", password_hash=hash_password("pass"), full_name="Other", role="admin")
        session.add(other_user)
        await session.flush()
        other_pos = await _make_position(session, other_tenant.id, other_user.id)
        other_cand = await _make_candidate(session, other_tenant.id, other_pos.id, name="Other", email="oc@other.com")
        await session.commit()
        other_cand_id = other_cand.id
    res = await client.delete(f"/api/v1/candidates/{other_cand_id}", headers=headers)
    assert res.status_code == 404
