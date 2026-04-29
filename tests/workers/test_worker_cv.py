"""Tests for cv_processing worker — all external calls mocked."""
import json
import uuid
from unittest.mock import MagicMock, patch
import pytest

def _claude_resp(content):
    text = json.dumps(content) if isinstance(content, (dict, list)) else content
    r = MagicMock(); r.content = [MagicMock(text=text)]; r.stop_reason = "end_turn"
    return r

PARSED = {"name": "Alice", "email": "a@t.com", "skills": ["Python", "FastAPI"], "experience_years": 4,
          "experiences": [{"title": "Dev", "company": "Acme", "duration": "4a", "description": "APIs"}],
          "education": [{"degree": "Master", "school": "UP", "year": "2019"}], "languages": ["FR"], "summary": "Dev backend.",
          "quality_score": {"score": 68, "explanation": {"technical_depth": {"score": 70, "justification": "OK"},
                           "experience_quality": {"score": 65, "justification": "OK"}, "education_relevance": {"score": 70, "justification": "OK"},
                           "cv_completeness": {"score": 65, "justification": "OK"}}}}
SCORE = {"score": 80, "explanation": {"skills_match": {"score": 85, "matched": ["Python"], "missing": [], "justification": "OK"},
         "experience_match": {"score": 75, "justification": "4a"}, "education_match": {"score": 80, "justification": "M"}}}
QUALITY = {"score": 68, "explanation": {"technical_depth": {"score": 70, "justification": "OK"},
           "experience_quality": {"score": 65, "justification": "OK"}, "education_relevance": {"score": 70, "justification": "OK"},
           "cv_completeness": {"score": 65, "justification": "OK"}}}


# ─── parse_pdf / parse_docx ─────────────────────────────────────────────────

def test_parse_pdf():
    page = MagicMock(); page.get_text.return_value = "Alice Python"
    doc = MagicMock(); doc.__iter__ = MagicMock(return_value=iter([page])); doc.close = MagicMock()
    with patch("fitz.open", return_value=doc):
        from app.workers.cv_processing import parse_pdf, extract_structured_data
        with patch("app.workers.cv_processing.extract_structured_data", return_value=PARSED):
            r = parse_pdf(b"%PDF")
    assert r == PARSED

def test_parse_docx():
    p1 = MagicMock(text="Alice"); p2 = MagicMock(text="Python")
    mock_doc = MagicMock(paragraphs=[p1, p2])
    # Document is imported locally: from docx import Document
    with patch("docx.Document", return_value=mock_doc):
        with patch("app.workers.cv_processing.extract_structured_data", return_value=PARSED):
            from app.workers.cv_processing import parse_docx
            r = parse_docx(b"PK")
    assert r == PARSED


# ─── extract_structured_data ────────────────────────────────────────────────

def test_extract_structured_data():
    mc = MagicMock(); mc.messages.create.return_value = _claude_resp(PARSED)
    ms = MagicMock(); ms.ANTHROPIC_API_KEY = "k"; ms.ANTHROPIC_MODEL = "m"
    # Anthropic and get_settings imported locally inside the function
    with patch("anthropic.Anthropic", return_value=mc), patch("app.core.config.get_settings", return_value=ms):
        from app.workers.cv_processing import extract_structured_data
        r = extract_structured_data("text")
    assert r["name"] == "Alice"

def test_extract_bad_json():
    bad = MagicMock(); bad.content = [MagicMock(text="NOT JSON")]; bad.stop_reason = "end_turn"
    mc = MagicMock(); mc.messages.create.return_value = bad
    ms = MagicMock(); ms.ANTHROPIC_API_KEY = "k"; ms.ANTHROPIC_MODEL = "m"
    with patch("anthropic.Anthropic", return_value=mc), patch("app.core.config.get_settings", return_value=ms):
        from app.workers.cv_processing import extract_structured_data
        r = extract_structured_data("text")
    assert r.get("parse_error") is True


# ─── score_cv ───────────────────────────────────────────────────────────────

def test_score_cv_custom_weights():
    mc = MagicMock(); mc.messages.create.return_value = _claude_resp(SCORE)
    ms = MagicMock(); ms.ANTHROPIC_API_KEY = "k"; ms.ANTHROPIC_MODEL = "m"
    pos = MagicMock(title="D", description="D", required_skills=["Python"], seniority_level="mid")
    with patch("anthropic.Anthropic", return_value=mc), patch("app.core.config.get_settings", return_value=ms):
        from app.workers.cv_processing import score_cv
        score_cv(PARSED, pos, weights={"skills": 60, "experience": 25, "education": 15})
    prompt = mc.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "60%" in prompt and "25%" in prompt and "15%" in prompt

def test_score_cv_quality_structure():
    mc = MagicMock(); mc.messages.create.return_value = _claude_resp(QUALITY)
    ms = MagicMock(); ms.ANTHROPIC_API_KEY = "k"; ms.ANTHROPIC_MODEL = "m"
    with patch("anthropic.Anthropic", return_value=mc), patch("app.core.config.get_settings", return_value=ms):
        from app.workers.cv_processing import score_cv_quality
        r = score_cv_quality(PARSED)
    assert r["score"] == 68
    for k in ("technical_depth", "experience_quality", "education_relevance", "cv_completeness"):
        assert k in r["explanation"]


# ─── process_cv pipeline ────────────────────────────────────────────────────

def _mock_session(candidate, position=None, tenant=None):
    sess = MagicMock()
    def _get(model, uid):
        name = model.__name__
        if name == "Candidate": return candidate
        if name == "Position": return position
        if name == "Tenant": return tenant
        return None
    sess.get.side_effect = _get

    # Mock session.query().filter().all() to return empty list (no applications)
    mock_query = MagicMock()
    mock_query.filter.return_value.all.return_value = []
    sess.query.return_value = mock_query

    return sess

def _make_cand(cv_path="cvs/f.pdf", pos_id=None, tid=None):
    c = MagicMock(); c.id = uuid.uuid4(); c.cv_file_path = cv_path
    c.position_id = uuid.UUID(pos_id) if pos_id else None
    c.tenant_id = tid or uuid.uuid4()
    c.cv_parsed_data = {}; c.cv_score = None; c.cv_score_explanation = None; c.pipeline_status = "new"
    return c

def _make_pos(pid=None, advance=75, reject=30):
    p = MagicMock(); p.id = pid or uuid.uuid4(); p.title = "D"; p.description = "D"
    p.required_skills = ["Python"]; p.seniority_level = "mid"
    p.auto_advance_threshold = advance; p.auto_reject_threshold = reject
    return p

def _make_tenant(s=50, e=30, ed=20):
    t = MagicMock(); t.scoring_skills_weight = s; t.scoring_experience_weight = e; t.scoring_education_weight = ed
    return t

def _run_process_cv(candidate_id, sess, score_result=SCORE, parsed=None, **kwargs):
    """Run process_cv with all external deps mocked."""
    import copy
    parsed = copy.deepcopy(parsed if parsed is not None else PARSED)
    with patch("app.workers.cv_processing.get_sync_session", return_value=sess), \
         patch("app.workers.cv_processing.parse_cv_file", return_value=parsed), \
         patch("app.workers.cv_processing.score_cv", return_value=score_result) as ms, \
         patch("app.workers.cv_processing.score_cv_quality", return_value=QUALITY) as mq, \
         patch("app.workers.notifications.send_consent_email", MagicMock()) as me, \
         patch("app.workers.question_generation.generate_questions", MagicMock()) as mg, \
         patch("app.workers.cv_processing._update_bulk_import_progress") as mu:
        from app.workers.cv_processing import process_cv
        process_cv(candidate_id, **kwargs)
        return ms, mq, me, mg, mu


def test_process_cv_full():
    pid = str(uuid.uuid4()); c = _make_cand(pos_id=pid); p = _make_pos(pid=uuid.UUID(pid)); t = _make_tenant()
    sess = _mock_session(c, p, t)
    ms, mq, me, mg, mu = _run_process_cv(str(c.id), sess, position_id=pid)
    assert c.cv_score == 80
    ms.assert_called_once()

def test_process_cv_no_file():
    c = _make_cand(cv_path=None); sess = MagicMock(); sess.get.return_value = c
    with patch("app.workers.cv_processing.get_sync_session", return_value=sess), \
         patch("app.workers.cv_processing.parse_cv_file") as mp:
        from app.workers.cv_processing import process_cv
        process_cv.__wrapped__(MagicMock(), str(uuid.uuid4()))
    mp.assert_not_called()

def test_process_cv_vivier():
    c = _make_cand(pos_id=None); t = _make_tenant(); sess = _mock_session(c, None, t)
    ms, mq, me, mg, mu = _run_process_cv(str(c.id), sess)
    ms.assert_not_called()  # score_cv not called (no position)
    # mq (score_cv_quality) no longer exists as separate call; quality comes from parsed_data
    assert c.cv_score == 68  # Quality score from PARSED
    assert c.profile_score == 68  # Also set from quality
    assert c.pipeline_status == "cv_analyzed"

def test_process_cv_bulk_import():
    bid = str(uuid.uuid4()); c = _make_cand(pos_id=None); t = _make_tenant()
    sess = _mock_session(c, None, t)
    ms, mq, me, mg, mu = _run_process_cv(str(c.id), sess, bulk_import_id=bid)
    mu.assert_called_once_with(sess, bid, True)

def test_auto_reject_flags_for_review():
    pid = str(uuid.uuid4()); c = _make_cand(pos_id=pid); p = _make_pos(pid=uuid.UUID(pid), reject=50); t = _make_tenant()
    sess = _mock_session(c, p, t)
    with patch("app.services.notification_service.create_notification") as mock_notif:
        _run_process_cv(str(c.id), sess, score_result={"score": 20, "explanation": {}}, position_id=pid)
    assert c.pipeline_status == "flagged_for_review"
    mock_notif.assert_called_once()
    call_kwargs = mock_notif.call_args.kwargs
    assert call_kwargs["type"] == "auto_flagged_for_review"
    assert "20" in call_kwargs["message"]
    assert "50" in call_kwargs["message"]

def test_auto_advance():
    pid = str(uuid.uuid4()); c = _make_cand(pos_id=pid); p = _make_pos(pid=uuid.UUID(pid), advance=75); t = _make_tenant()
    sess = _mock_session(c, p, t)
    _run_process_cv(str(c.id), sess, score_result={"score": 90, "explanation": {}}, position_id=pid)
    assert c.pipeline_status == "invited"


# ─── _update_bulk_import_progress ───────────────────────────────────────────

def test_update_progress_success():
    from app.workers.cv_processing import _update_bulk_import_progress
    bi = MagicMock(processed_count=3, total_count=10, status="processing")
    sess = MagicMock(); sess.get.return_value = bi
    _update_bulk_import_progress(sess, str(uuid.uuid4()), True)
    sess.execute.assert_called_once()

def test_update_progress_completes():
    from app.workers.cv_processing import _update_bulk_import_progress
    bi = MagicMock(processed_count=5, total_count=5, status="processing", completed_at=None, error_count=0)
    sess = MagicMock(); sess.get.return_value = bi
    _update_bulk_import_progress(sess, str(uuid.uuid4()), True)
    assert bi.status == "completed"
    assert bi.completed_at is not None

def test_update_progress_completed_with_errors():
    from app.workers.cv_processing import _update_bulk_import_progress
    bi = MagicMock(processed_count=5, total_count=5, status="processing", completed_at=None, error_count=2)
    sess = MagicMock(); sess.get.return_value = bi
    _update_bulk_import_progress(sess, str(uuid.uuid4()), False)
    assert bi.status == "completed_with_errors"
    assert bi.completed_at is not None


# ─── cv_processing status ──────────────────────────────────────────────────

def test_process_cv_sets_processing_status():
    """process_cv sets pipeline_status to 'cv_processing' at start."""
    pid = str(uuid.uuid4()); c = _make_cand(pos_id=pid); p = _make_pos(pid=uuid.UUID(pid)); t = _make_tenant()
    sess = _mock_session(c, p, t)
    statuses = []
    orig_commit = sess.commit
    def track_commit():
        statuses.append(c.pipeline_status)
        orig_commit()
    sess.commit = track_commit
    _run_process_cv(str(c.id), sess, position_id=pid)
    assert "cv_processing" in statuses  # First commit sets cv_processing

def test_process_cv_error_sets_failed():
    """process_cv sets pipeline_status to 'cv_failed' on error."""
    c = _make_cand(); t = _make_tenant(); sess = _mock_session(c, None, t)
    with patch("app.workers.cv_processing.get_sync_session", return_value=sess), \
         patch("app.workers.cv_processing.parse_cv_file", side_effect=RuntimeError("broken")):
        from app.workers.cv_processing import process_cv
        process_cv(str(c.id))
    assert c.pipeline_status == "cv_failed"
