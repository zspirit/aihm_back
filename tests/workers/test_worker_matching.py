"""Tests for matching worker — all mocked, no DB."""
import json
import uuid
from unittest.mock import MagicMock, patch
import pytest

TENANT_ID = uuid.uuid4()
POS_ID = uuid.uuid4()
SESSION_ID = uuid.uuid4()
CID1 = uuid.uuid4()
CID2 = uuid.uuid4()

def _session(status="pending", pos_ids=None):
    s = MagicMock()
    s.id = SESSION_ID; s.tenant_id = TENANT_ID; s.status = status
    s.position_ids = pos_ids or [str(POS_ID)]; s.candidate_ids = None
    s.computed_pairs = 0; s.completed_at = None
    return s

def _candidates():
    return [
        {"candidate_id": str(CID1), "name": "Alice", "cv_parsed_data": {"skills": ["Python"]},
         "cv_score": 80, "source_position_id": str(POS_ID), "source_position_title": "Dev"},
        {"candidate_id": str(CID2), "name": "Bob", "cv_parsed_data": {"skills": ["Python"]},
         "cv_score": 65, "source_position_id": str(POS_ID), "source_position_title": "Dev"},
    ]

def _pos():
    return {"title": "Backend", "description": "D", "required_skills": ["Python"], "seniority_level": "mid"}

def _matches(cands):
    return [{"candidate_id": c["candidate_id"], "match_score": 82, "match_reasons": {"skills_match": {"score": 85}}} for c in cands]

def _claude_resp(content):
    r = MagicMock(); r.content = [MagicMock(text=json.dumps(content))]; r.stop_reason = "end_turn"
    return r

def _factory(session):
    f = MagicMock(); db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = session
    f.return_value.__enter__ = MagicMock(return_value=db)
    f.return_value.__exit__ = MagicMock(return_value=False)
    return f, db


def test_compute_batch():
    session = _session()
    f, db = _factory(session)
    with patch("app.core.database.sync_session_factory", f), \
         patch("app.services.batch_matching._load_candidates", return_value=_candidates()), \
         patch("app.services.batch_matching._load_position_data", return_value=_pos()), \
         patch("app.services.batch_matching._upsert_scores", return_value=2) as mu, \
         patch("app.services.batch_matching.ai_score_matches", return_value=_matches(_candidates())):
        from app.services.batch_matching import compute_batch_matching
        compute_batch_matching(str(SESSION_ID))
    mu.assert_called_once()

def test_compute_skips_empty():
    session = _session()
    f, db = _factory(session)
    with patch("app.core.database.sync_session_factory", f), \
         patch("app.services.batch_matching._load_candidates", return_value=[]), \
         patch("app.services.batch_matching.ai_score_matches") as mai:
        from app.services.batch_matching import compute_batch_matching
        compute_batch_matching(str(SESSION_ID))
    mai.assert_not_called()
    assert session.status == "completed"

def test_compute_updates_status():
    session = _session()
    log = []
    f, db = _factory(session)
    db.commit.side_effect = lambda: log.append(session.status)
    with patch("app.core.database.sync_session_factory", f), \
         patch("app.services.batch_matching._load_candidates", return_value=_candidates()), \
         patch("app.services.batch_matching._load_position_data", return_value=_pos()), \
         patch("app.services.batch_matching._upsert_scores", return_value=2), \
         patch("app.services.batch_matching.ai_score_matches", return_value=_matches(_candidates())):
        from app.services.batch_matching import compute_batch_matching
        compute_batch_matching(str(SESSION_ID))
    assert log[-1] == "completed"

def test_compute_handles_error():
    session = _session(pos_ids=[str(POS_ID), str(uuid.uuid4())])
    idx = {"n": 0}
    def se(batch, pos, limit):
        idx["n"] += 1
        if idx["n"] == 1: raise RuntimeError("timeout")
        return _matches(batch)
    f, db = _factory(session)
    with patch("app.core.database.sync_session_factory", f), \
         patch("app.services.batch_matching._load_candidates", return_value=_candidates()), \
         patch("app.services.batch_matching._load_position_data", return_value=_pos()), \
         patch("app.services.batch_matching._upsert_scores", return_value=2), \
         patch("app.services.batch_matching.ai_score_matches", side_effect=se):
        from app.services.batch_matching import compute_batch_matching
        compute_batch_matching(str(SESSION_ID))
    assert session.status == "completed"

def test_score_single_pair():
    from app.services.matching import ai_score_matches
    cands = [_candidates()[0]]
    matches = [{"candidate_id": str(CID1), "match_score": 82, "match_reasons": {"skills_match": {"score": 85}}}]
    expected = {"matches": matches}
    mc = MagicMock(); mc.messages.create.return_value = _claude_resp(expected)
    ms = MagicMock(); ms.ANTHROPIC_API_KEY = "k"; ms.ANTHROPIC_MODEL = "m"
    with patch("app.services.matching.Anthropic", return_value=mc), patch("app.services.matching.get_settings", return_value=ms):
        result = ai_score_matches(cands, _pos(), limit=20)
    assert len(result) == 1
    assert result[0]["match_score"] == 82
