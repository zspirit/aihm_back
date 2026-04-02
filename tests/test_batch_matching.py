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


# ─── Helpers ────────────────────────────────────────────────────────────────

async def _pos(db, tid, uid, title="Backend Dev"):
    p = Position(tenant_id=tid, title=title, description="T", required_skills=["Python"], seniority_level="mid", created_by=uid)
    db.add(p); await db.flush(); return p

async def _cand(db, tid, name="Alice", email="a@t.com", phone="+33612345678", parsed=True):
    c = Candidate(tenant_id=tid, name=name, email=email, phone=phone, cv_parsed_data={"skills":["Python"]} if parsed else None)
    db.add(c); await db.flush(); return c

async def _score(db, tid, cid, pid, score=82.0):
    ms = MatchScore(tenant_id=tid, candidate_id=cid, position_id=pid, score=score, reasons={"skills_match":{"score":85}})
    db.add(ms); await db.flush(); return ms

async def _session(db, tid, uid, pids, cids):
    s = MatchSession(tenant_id=tid, user_id=uid, position_ids=[str(p) for p in pids], candidate_ids=[str(c) for c in cids],
                     status="completed", total_pairs=len(pids)*len(cids), computed_pairs=len(pids)*len(cids))
    db.add(s); await db.flush(); return s

@pytest.fixture()
def mock_celery():
    with patch("app.workers.matching.compute_match_matrix.delay", MagicMock()), \
         patch("app.workers.notifications.send_consent_email.delay", MagicMock()), \
         patch("app.workers.telephony.initiate_call.delay", MagicMock()):
        yield

@pytest_asyncio.fixture()
async def data(db_session, admin_data):
    h, u, t = admin_data
    p = await _pos(db_session, t.id, u.id)
    c1 = await _cand(db_session, t.id, "Alice", "alice@t.com")
    c2 = await _cand(db_session, t.id, "Bob", "bob@t.com")
    await db_session.commit()
    return h, u, t, p, c1, c2

@pytest_asyncio.fixture()
async def scored(db_session, data):
    h, u, t, p, c1, c2 = data
    ms1 = await _score(db_session, t.id, c1.id, p.id, 82.0)
    ms2 = await _score(db_session, t.id, c2.id, p.id, 65.0)
    await db_session.commit()
    return h, u, t, p, c1, c2, ms1, ms2

@pytest_asyncio.fixture()
async def with_session(db_session, scored):
    h, u, t, p, c1, c2, ms1, ms2 = scored
    s = await _session(db_session, t.id, u.id, [p.id], [c1.id, c2.id])
    await db_session.commit()
    return h, u, t, p, c1, c2, ms1, ms2, s


# ═══ 1. Create session ═══

@pytest.mark.asyncio
async def test_create_session(client, data, mock_celery):
    h, u, t, p, c1, c2 = data
    res = await client.post("/api/v1/matching/sessions", headers=h, json={"position_ids": [str(p.id)]})
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
    h, u, t, p, c1, c2, ms1, ms2, s = with_session
    res = await client.get("/api/v1/matching/sessions", headers=h)
    assert res.status_code == 200
    ids = [x["id"] for x in res.json()]
    assert str(s.id) in ids


# ═══ 4. Get session status ═══

@pytest.mark.asyncio
async def test_get_session_status(client, with_session):
    h, *_, s = with_session
    res = await client.get(f"/api/v1/matching/sessions/{s.id}", headers=h)
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
    h, u, t, p, c1, c2, ms1, ms2 = scored
    res = await client.get("/api/v1/matching/matrix", headers=h, params={"position_ids": str(p.id)})
    assert res.status_code == 200
    d = res.json()
    assert d["total_candidates"] == 2
    assert len(d["scores"]) == 2

@pytest.mark.asyncio
async def test_get_matrix_min_score(client, scored):
    h, u, t, p, c1, c2, *_ = scored
    res = await client.get("/api/v1/matching/matrix", headers=h, params={"position_ids": str(p.id), "min_score": 70})
    assert res.status_code == 200
    assert res.json()["total_candidates"] == 1

@pytest.mark.asyncio
async def test_get_matrix_empty(client, data):
    h, u, t, p, c1, c2 = data
    res = await client.get("/api/v1/matching/matrix", headers=h, params={"position_ids": str(p.id)})
    assert res.status_code == 200
    assert res.json()["total_candidates"] == 0


# ═══ 6. Get matrix by session_id ═══

@pytest.mark.asyncio
async def test_get_matrix_by_session(client, with_session):
    h, *_, s = with_session
    res = await client.get("/api/v1/matching/matrix", headers=h, params={"session_id": str(s.id)})
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
    h, u, t, p, c1, *_ = scored
    res = await client.post("/api/v1/matching/assign", headers=h, json={"assignments": [{"candidate_id": str(c1.id), "position_id": str(p.id)}]})
    assert res.status_code == 200
    assert res.json()["results"][0]["status"] == "assigned"

@pytest.mark.asyncio
async def test_assign_duplicate_skipped(client, scored):
    h, u, t, p, c1, *_ = scored
    await client.post("/api/v1/matching/assign", headers=h, json={"assignments": [{"candidate_id": str(c1.id), "position_id": str(p.id)}]})
    res = await client.post("/api/v1/matching/assign", headers=h, json={"assignments": [{"candidate_id": str(c1.id), "position_id": str(p.id)}]})
    assert res.json()["results"][0]["status"] == "skipped"

@pytest.mark.asyncio
async def test_assign_empty(client, admin_data):
    h, _, _ = admin_data
    res = await client.post("/api/v1/matching/assign", headers=h, json={"assignments": []})
    assert res.status_code == 400


# ═══ 9. Unassign ═══

@pytest.mark.asyncio
async def test_unassign(client, scored, db_session):
    h, u, t, p, c1, *_ = scored
    await client.post("/api/v1/matching/assign", headers=h, json={"assignments": [{"candidate_id": str(c1.id), "position_id": str(p.id)}]})
    res = await client.post("/api/v1/matching/unassign", headers=h, json={"assignments": [{"candidate_id": str(c1.id), "position_id": str(p.id)}]})
    assert res.json()["results"][0]["status"] == "unassigned"
    r = await db_session.execute(select(Application).where(Application.candidate_id == c1.id, Application.position_id == p.id))
    assert r.scalar_one_or_none() is None

@pytest.mark.asyncio
async def test_unassign_not_found(client, data):
    h, u, t, p, c1, *_ = data
    res = await client.post("/api/v1/matching/unassign", headers=h, json={"assignments": [{"candidate_id": str(c1.id), "position_id": str(p.id)}]})
    assert res.json()["results"][0]["status"] == "not_found"


# ═══ 10. Toggle assign/unassign ═══

@pytest.mark.asyncio
async def test_toggle(client, scored, db_session):
    h, u, t, p, c1, *_ = scored
    pair = {"candidate_id": str(c1.id), "position_id": str(p.id)}
    r1 = await client.post("/api/v1/matching/assign", headers=h, json={"assignments": [pair]})
    assert r1.json()["results"][0]["status"] == "assigned"
    r2 = await client.post("/api/v1/matching/unassign", headers=h, json={"assignments": [pair]})
    assert r2.json()["results"][0]["status"] == "unassigned"
    r3 = await client.post("/api/v1/matching/assign", headers=h, json={"assignments": [pair]})
    assert r3.json()["results"][0]["status"] == "assigned"


# ═══ 11. Assigned pairs ═══

@pytest.mark.asyncio
async def test_assigned_pairs(client, scored):
    h, u, t, p, c1, c2, *_ = scored
    await client.post("/api/v1/matching/assign", headers=h, json={"assignments": [
        {"candidate_id": str(c1.id), "position_id": str(p.id)},
        {"candidate_id": str(c2.id), "position_id": str(p.id)},
    ]})
    res = await client.get("/api/v1/matching/assigned-pairs", headers=h, params={"candidate_ids": f"{c1.id},{c2.id}", "position_ids": str(p.id)})
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
    h, u, t, p, c1, c2 = data
    res = await client.post("/api/v1/matching/bulk-action", headers=h, json={"action": "send_consent", "candidate_ids": [str(c1.id), str(c2.id)]})
    assert res.status_code == 200
    assert res.json()["success"] == 2

@pytest.mark.asyncio
async def test_bulk_consent_already_given(client, data, db_session):
    h, u, t, p, c1, *_ = data
    db_session.add(Consent(candidate_id=c1.id, token="tok", type="call_recording", granted=True))
    await db_session.commit()
    with patch("app.workers.notifications.send_consent_email.delay", MagicMock()):
        res = await client.post("/api/v1/matching/bulk-action", headers=h, json={"action": "send_consent", "candidate_ids": [str(c1.id)]})
    assert res.json()["results"][0]["status"] == "skipped"

@pytest.mark.asyncio
async def test_bulk_action_invalid(client, data):
    h, *_ = data
    res = await client.post("/api/v1/matching/bulk-action", headers=h, json={"action": "nope", "candidate_ids": [str(uuid.uuid4())]})
    assert res.status_code == 400

@pytest.mark.asyncio
async def test_bulk_action_empty(client, admin_data):
    h, _, _ = admin_data
    res = await client.post("/api/v1/matching/bulk-action", headers=h, json={"action": "send_consent", "candidate_ids": []})
    assert res.status_code == 400


# ═══ 13. Bulk action: assign_all ═══

@pytest.mark.asyncio
async def test_bulk_assign_all(client, scored, db_session):
    h, u, t, p, c1, c2, *_ = scored
    res = await client.post("/api/v1/matching/bulk-action", headers=h, json={"action": "assign_all", "candidate_ids": [str(c1.id), str(c2.id)], "position_id": str(p.id)})
    assert res.status_code == 200
    assert res.json()["success"] == 2

@pytest.mark.asyncio
async def test_bulk_assign_no_position(client, data):
    h, u, t, p, c1, *_ = data
    res = await client.post("/api/v1/matching/bulk-action", headers=h, json={"action": "assign_all", "candidate_ids": [str(c1.id)]})
    assert res.status_code == 400


# ═══ 14. Bulk action: schedule_calls ═══

@pytest.mark.asyncio
async def test_bulk_schedule_calls(client, data, db_session, mock_celery):
    h, u, t, p, c1, *_ = data
    c1.position_id = p.id
    db_session.add(Consent(candidate_id=c1.id, token="tok-call", type="call_recording", granted=True))
    await db_session.commit()
    res = await client.post("/api/v1/matching/bulk-action", headers=h, json={"action": "schedule_calls", "candidate_ids": [str(c1.id)]})
    assert res.status_code == 200
    assert res.json()["results"][0]["status"] == "ok"

@pytest.mark.asyncio
async def test_bulk_schedule_no_consent(client, data):
    h, u, t, p, c1, *_ = data
    res = await client.post("/api/v1/matching/bulk-action", headers=h, json={"action": "schedule_calls", "candidate_ids": [str(c1.id)]})
    assert res.json()["results"][0]["status"] == "error"


# ═══ 15. Delete session ═══

@pytest.mark.asyncio
async def test_delete_session(client, with_session, db_session):
    h, *_, s = with_session
    res = await client.delete(f"/api/v1/matching/sessions/{s.id}", headers=h)
    assert res.status_code == 204
    r = await db_session.execute(select(MatchSession).where(MatchSession.id == s.id))
    assert r.scalar_one_or_none() is None

@pytest.mark.asyncio
async def test_delete_session_not_found(client, admin_data):
    h, _, _ = admin_data
    res = await client.delete(f"/api/v1/matching/sessions/{uuid.uuid4()}", headers=h)
    assert res.status_code == 404


# ═══ 16. Bulk delete sessions ═══

@pytest.mark.asyncio
async def test_bulk_delete_sessions(client, db_session, scored):
    h, u, t, p, c1, c2, *_ = scored
    s1 = await _session(db_session, t.id, u.id, [p.id], [c1.id])
    s2 = await _session(db_session, t.id, u.id, [p.id], [c2.id])
    await db_session.commit()
    res = await client.post("/api/v1/matching/sessions/bulk-delete", headers=h, json={"ids": [str(s1.id), str(s2.id)]})
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
