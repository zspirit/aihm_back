"""Comprehensive tests for batch matching endpoints."""
import uuid
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.candidate import Candidate
from app.models.consent import Consent
from app.models.match_score import MatchScore, MatchSession
from app.models.position import Position
from app.models.application import Application

from tests.conftest import _create_user, TestSession


# ─── Helpers ────────────────────────────────────────────────────────────────

async def _pos(session, tid, uid, title="Backend Dev"):
    p = Position(tenant_id=tid, title=title, description="T", required_skills=["Python"], seniority_level="mid", created_by=uid)
    session.add(p); await session.flush(); return p

async def _cand(session, tid, name="Alice", email="a@t.com", phone="+33612345678", parsed=True):
    c = Candidate(tenant_id=tid, name=name, email=email, phone=phone, cv_parsed_data={"skills":["Python"]} if parsed else None)
    session.add(c); await session.flush(); return c

async def _score(session, tid, cid, pid, score=82.0):
    ms = MatchScore(tenant_id=tid, candidate_id=cid, position_id=pid, score=score, reasons={"skills_match":{"score":85}})
    session.add(ms); await session.flush(); return ms

async def _session_obj(session, tid, uid, pids, cids):
    s = MatchSession(tenant_id=tid, user_id=uid, position_ids=[str(p) for p in pids], candidate_ids=[str(c) for c in cids],
                     status="completed", total_pairs=len(pids)*len(cids), computed_pairs=len(pids)*len(cids))
    session.add(s); await session.flush(); return s

@pytest.fixture()
def mock_celery():
    with patch("app.workers.matching.compute_match_matrix.delay", MagicMock()), \
         patch("app.workers.notifications.send_consent_email.delay", MagicMock()), \
         patch("app.workers.telephony.initiate_call.delay", MagicMock()):
        yield


@pytest_asyncio.fixture()
async def admin_data(_setup_db):
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "admin@test.com", "admin")
        user_id = user.id
        tenant_id = tenant.id
    return headers, user_id, tenant_id


@pytest_asyncio.fixture()
async def viewer_headers(_setup_db):
    async with TestSession() as session:
        headers, _, _ = await _create_user(session, "viewer@test.com", "viewer", "Viewer Corp")
    return headers


@pytest_asyncio.fixture()
async def data(_setup_db):
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "admin@test.com", "admin")
        p = await _pos(session, tenant.id, user.id)
        c1 = await _cand(session, tenant.id, "Alice", "alice@t.com")
        c2 = await _cand(session, tenant.id, "Bob", "bob@t.com")
        await session.commit()
        result = {
            "h": headers, "user_id": user.id, "tenant_id": tenant.id,
            "pos_id": p.id, "c1_id": c1.id, "c2_id": c2.id,
        }
    return result

@pytest_asyncio.fixture()
async def scored(_setup_db):
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "admin@test.com", "admin")
        p = await _pos(session, tenant.id, user.id)
        c1 = await _cand(session, tenant.id, "Alice", "alice@t.com")
        c2 = await _cand(session, tenant.id, "Bob", "bob@t.com")
        ms1 = await _score(session, tenant.id, c1.id, p.id, 82.0)
        ms2 = await _score(session, tenant.id, c2.id, p.id, 65.0)
        await session.commit()
        result = {
            "h": headers, "user_id": user.id, "tenant_id": tenant.id,
            "pos_id": p.id, "c1_id": c1.id, "c2_id": c2.id,
            "ms1_id": ms1.id, "ms2_id": ms2.id,
        }
    return result

@pytest_asyncio.fixture()
async def with_session(_setup_db):
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "admin@test.com", "admin")
        p = await _pos(session, tenant.id, user.id)
        c1 = await _cand(session, tenant.id, "Alice", "alice@t.com")
        c2 = await _cand(session, tenant.id, "Bob", "bob@t.com")
        ms1 = await _score(session, tenant.id, c1.id, p.id, 82.0)
        ms2 = await _score(session, tenant.id, c2.id, p.id, 65.0)
        s = await _session_obj(session, tenant.id, user.id, [p.id], [c1.id, c2.id])
        await session.commit()
        result = {
            "h": headers, "user_id": user.id, "tenant_id": tenant.id,
            "pos_id": p.id, "c1_id": c1.id, "c2_id": c2.id,
            "ms1_id": ms1.id, "ms2_id": ms2.id, "session_id": s.id,
        }
    return result


# ═══ 1. Create session ═══

@pytest.mark.asyncio
async def test_create_session(client, data, mock_celery):
    d = data
    res = await client.post("/api/v1/matching/sessions", headers=d["h"], json={"position_ids": [str(d["pos_id"])]})
    assert res.status_code == 202
    assert res.json()["status"] == "pending"
    assert res.json()["total_pairs"] == 2

@pytest.mark.asyncio
async def test_create_session_no_positions(client, admin_data):
    h, _, _ = admin_data
    res = await client.post("/api/v1/matching/sessions", headers=h, json={"position_ids": []})
    assert res.status_code == 400

@pytest.mark.asyncio
async def test_create_session_unknown_position(client, admin_data, mock_celery):
    h, _, _ = admin_data
    res = await client.post("/api/v1/matching/sessions", headers=h, json={"position_ids": [str(uuid.uuid4())]})
    assert res.status_code == 404


# ═══ 3. List sessions ═══

@pytest.mark.asyncio
async def test_list_sessions(client, with_session):
    d = with_session
    res = await client.get("/api/v1/matching/sessions", headers=d["h"])
    assert res.status_code == 200
    ids = [x["id"] for x in res.json()]
    assert str(d["session_id"]) in ids


# ═══ 4. Get session status ═══

@pytest.mark.asyncio
async def test_get_session_status(client, with_session):
    d = with_session
    res = await client.get(f"/api/v1/matching/sessions/{d['session_id']}", headers=d["h"])
    assert res.status_code == 200
    assert res.json()["status"] == "completed"

@pytest.mark.asyncio
async def test_get_session_not_found(client, admin_data):
    h, _, _ = admin_data
    res = await client.get(f"/api/v1/matching/sessions/{uuid.uuid4()}", headers=h)
    assert res.status_code == 404


# ═══ 5. Get matrix by position_ids ═══

@pytest.mark.asyncio
async def test_get_matrix(client, scored):
    d = scored
    res = await client.get("/api/v1/matching/matrix", headers=d["h"], params={"position_ids": str(d["pos_id"])})
    assert res.status_code == 200
    body = res.json()
    assert body["total_candidates"] == 2
    assert len(body["scores"]) == 2

@pytest.mark.asyncio
async def test_get_matrix_min_score(client, scored):
    d = scored
    res = await client.get("/api/v1/matching/matrix", headers=d["h"], params={"position_ids": str(d["pos_id"]), "min_score": 70})
    assert res.status_code == 200
    assert res.json()["total_candidates"] == 1

@pytest.mark.asyncio
async def test_get_matrix_empty(client, data):
    d = data
    res = await client.get("/api/v1/matching/matrix", headers=d["h"], params={"position_ids": str(d["pos_id"])})
    assert res.status_code == 200
    assert res.json()["total_candidates"] == 0


# ═══ 6. Get matrix by session_id ═══

@pytest.mark.asyncio
async def test_get_matrix_by_session(client, with_session):
    d = with_session
    res = await client.get("/api/v1/matching/matrix", headers=d["h"], params={"session_id": str(d["session_id"])})
    assert res.status_code == 200
    assert res.json()["total_candidates"] == 2

@pytest.mark.asyncio
async def test_get_matrix_session_not_found(client, admin_data):
    h, _, _ = admin_data
    res = await client.get("/api/v1/matching/matrix", headers=h, params={"session_id": str(uuid.uuid4())})
    assert res.status_code == 404


# ═══ 8. Assign ═══

@pytest.mark.asyncio
async def test_assign(client, scored):
    d = scored
    res = await client.post("/api/v1/matching/assign", headers=d["h"], json={"assignments": [{"candidate_id": str(d["c1_id"]), "position_id": str(d["pos_id"])}]})
    assert res.status_code == 200
    assert res.json()["results"][0]["status"] == "assigned"

@pytest.mark.asyncio
async def test_assign_duplicate_skipped(client, scored):
    d = scored
    await client.post("/api/v1/matching/assign", headers=d["h"], json={"assignments": [{"candidate_id": str(d["c1_id"]), "position_id": str(d["pos_id"])}]})
    res = await client.post("/api/v1/matching/assign", headers=d["h"], json={"assignments": [{"candidate_id": str(d["c1_id"]), "position_id": str(d["pos_id"])}]})
    assert res.json()["results"][0]["status"] == "skipped"

@pytest.mark.asyncio
async def test_assign_empty(client, admin_data):
    h, _, _ = admin_data
    res = await client.post("/api/v1/matching/assign", headers=h, json={"assignments": []})
    assert res.status_code == 400


# ═══ 9. Unassign ═══

@pytest.mark.asyncio
async def test_unassign(client, scored):
    d = scored
    await client.post("/api/v1/matching/assign", headers=d["h"], json={"assignments": [{"candidate_id": str(d["c1_id"]), "position_id": str(d["pos_id"])}]})
    res = await client.post("/api/v1/matching/unassign", headers=d["h"], json={"assignments": [{"candidate_id": str(d["c1_id"]), "position_id": str(d["pos_id"])}]})
    assert res.json()["results"][0]["status"] == "unassigned"

@pytest.mark.asyncio
async def test_unassign_not_found(client, data):
    d = data
    res = await client.post("/api/v1/matching/unassign", headers=d["h"], json={"assignments": [{"candidate_id": str(d["c1_id"]), "position_id": str(d["pos_id"])}]})
    assert res.json()["results"][0]["status"] == "not_found"


# ═══ 10. Toggle assign/unassign ═══

@pytest.mark.asyncio
async def test_toggle(client, scored):
    d = scored
    pair = {"candidate_id": str(d["c1_id"]), "position_id": str(d["pos_id"])}
    r1 = await client.post("/api/v1/matching/assign", headers=d["h"], json={"assignments": [pair]})
    assert r1.json()["results"][0]["status"] == "assigned"
    r2 = await client.post("/api/v1/matching/unassign", headers=d["h"], json={"assignments": [pair]})
    assert r2.json()["results"][0]["status"] == "unassigned"
    r3 = await client.post("/api/v1/matching/assign", headers=d["h"], json={"assignments": [pair]})
    assert r3.json()["results"][0]["status"] == "assigned"


# ═══ 11. Assigned pairs ═══

@pytest.mark.asyncio
async def test_assigned_pairs(client, scored):
    d = scored
    await client.post("/api/v1/matching/assign", headers=d["h"], json={"assignments": [
        {"candidate_id": str(d["c1_id"]), "position_id": str(d["pos_id"])},
        {"candidate_id": str(d["c2_id"]), "position_id": str(d["pos_id"])},
    ]})
    res = await client.get("/api/v1/matching/assigned-pairs", headers=d["h"], params={"candidate_ids": f"{d['c1_id']},{d['c2_id']}", "position_ids": str(d["pos_id"])})
    assert res.status_code == 200
    assert len(res.json()["pairs"]) == 2

@pytest.mark.asyncio
async def test_assigned_pairs_empty(client, admin_data):
    h, _, _ = admin_data
    res = await client.get("/api/v1/matching/assigned-pairs", headers=h, params={"candidate_ids": "", "position_ids": ""})
    assert res.json()["pairs"] == []


# ═══ 12. Bulk action: send_consent ═══

@pytest.mark.asyncio
async def test_bulk_send_consent(client, data, mock_celery):
    d = data
    res = await client.post("/api/v1/matching/bulk-action", headers=d["h"], json={"action": "send_consent", "candidate_ids": [str(d["c1_id"]), str(d["c2_id"])]})
    assert res.status_code == 200
    assert res.json()["success"] == 2

@pytest.mark.asyncio
async def test_bulk_consent_already_given(client, data):
    d = data
    async with TestSession() as session:
        session.add(Consent(candidate_id=d["c1_id"], token="tok", type="call_recording", granted=True))
        await session.commit()
    with patch("app.workers.notifications.send_consent_email.delay", MagicMock()):
        res = await client.post("/api/v1/matching/bulk-action", headers=d["h"], json={"action": "send_consent", "candidate_ids": [str(d["c1_id"])]})
    assert res.json()["results"][0]["status"] == "skipped"

@pytest.mark.asyncio
async def test_bulk_action_invalid(client, data):
    d = data
    res = await client.post("/api/v1/matching/bulk-action", headers=d["h"], json={"action": "nope", "candidate_ids": [str(uuid.uuid4())]})
    assert res.status_code == 400

@pytest.mark.asyncio
async def test_bulk_action_empty(client, admin_data):
    h, _, _ = admin_data
    res = await client.post("/api/v1/matching/bulk-action", headers=h, json={"action": "send_consent", "candidate_ids": []})
    assert res.status_code == 400


# ═══ 13. Bulk action: assign_all ═══

@pytest.mark.asyncio
async def test_bulk_assign_all(client, scored):
    d = scored
    res = await client.post("/api/v1/matching/bulk-action", headers=d["h"], json={"action": "assign_all", "candidate_ids": [str(d["c1_id"]), str(d["c2_id"])], "position_id": str(d["pos_id"])})
    assert res.status_code == 200
    assert res.json()["success"] == 2

@pytest.mark.asyncio
async def test_bulk_assign_no_position(client, data):
    d = data
    res = await client.post("/api/v1/matching/bulk-action", headers=d["h"], json={"action": "assign_all", "candidate_ids": [str(d["c1_id"])]})
    assert res.status_code == 400


# ═══ 14. Bulk action: schedule_calls ═══

@pytest.mark.asyncio
async def test_bulk_schedule_calls(client, data, mock_celery):
    d = data
    async with TestSession() as session:
        from sqlalchemy import select as sa_select
        result = await session.execute(sa_select(Candidate).where(Candidate.id == d["c1_id"]))
        c1 = result.scalar_one()
        c1.position_id = d["pos_id"]
        session.add(Consent(candidate_id=d["c1_id"], token="tok-call", type="call_recording", granted=True))
        await session.commit()
    res = await client.post("/api/v1/matching/bulk-action", headers=d["h"], json={"action": "schedule_calls", "candidate_ids": [str(d["c1_id"])]})
    assert res.status_code == 200
    assert res.json()["results"][0]["status"] == "ok"

@pytest.mark.asyncio
async def test_bulk_schedule_no_consent(client, data):
    d = data
    res = await client.post("/api/v1/matching/bulk-action", headers=d["h"], json={"action": "schedule_calls", "candidate_ids": [str(d["c1_id"])]})
    assert res.json()["results"][0]["status"] == "error"


# ═══ 15. Delete session ═══

@pytest.mark.asyncio
async def test_delete_session(client, with_session):
    d = with_session
    res = await client.delete(f"/api/v1/matching/sessions/{d['session_id']}", headers=d["h"])
    assert res.status_code == 204

@pytest.mark.asyncio
async def test_delete_session_not_found(client, admin_data):
    h, _, _ = admin_data
    res = await client.delete(f"/api/v1/matching/sessions/{uuid.uuid4()}", headers=h)
    assert res.status_code == 404


# ═══ 16. Bulk delete sessions ═══

@pytest.mark.asyncio
async def test_bulk_delete_sessions(client, scored):
    d = scored
    async with TestSession() as session:
        s1 = await _session_obj(session, d["tenant_id"], d["user_id"], [d["pos_id"]], [d["c1_id"]])
        s2 = await _session_obj(session, d["tenant_id"], d["user_id"], [d["pos_id"]], [d["c2_id"]])
        await session.commit()
        s1_id = str(s1.id)
        s2_id = str(s2.id)
    res = await client.post("/api/v1/matching/sessions/bulk-delete", headers=d["h"], json={"ids": [s1_id, s2_id]})
    assert res.status_code == 200
    assert res.json()["deleted"] == 2

@pytest.mark.asyncio
async def test_bulk_delete_empty(client, admin_data):
    h, _, _ = admin_data
    res = await client.post("/api/v1/matching/sessions/bulk-delete", headers=h, json={"ids": []})
    assert res.status_code == 400


# ═══ Auth guards ═══

@pytest.mark.asyncio
async def test_viewer_cannot_create_session(client, viewer_headers):
    res = await client.post("/api/v1/matching/sessions", headers=viewer_headers, json={"position_ids": [str(uuid.uuid4())]})
    assert res.status_code in (401, 403)

@pytest.mark.asyncio
async def test_viewer_cannot_assign(client, viewer_headers):
    res = await client.post("/api/v1/matching/assign", headers=viewer_headers, json={"assignments": [{"candidate_id": str(uuid.uuid4()), "position_id": str(uuid.uuid4())}]})
    assert res.status_code in (401, 403)
