"""
Comprehensive tests for CV scoring pipeline.
Covers: score_cv, score_cv_quality, tenant weights, anti-stuffing,
auto-reject/advance, reprocess-cv, competence-dossier, profile/export, error handling.
"""
import json
import uuid
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from tests.conftest import _create_user, TestSession, TestSyncSession
from tests.conftest_mocks import MOCK_CV_PARSED, MOCK_CV_QUALITY, MOCK_CV_SCORE, _make_claude_response


# ─── Helpers ────────────────────────────────────────────────────────────────

async def _inject_candidate(session, tenant_id, position_id=None, name="Candidat",
                            cv_file_path=None, cv_parsed_data=None, cv_score=None, pipeline_status="new"):
    from app.models.candidate import Candidate
    cand = Candidate(
        tenant_id=tenant_id, position_id=position_id, name=name,
        email=f"{name.replace(' ','.').lower()}@test.com",
        cv_file_path=cv_file_path, cv_parsed_data=cv_parsed_data,
        cv_score=cv_score, pipeline_status=pipeline_status,
    )
    session.add(cand)
    await session.flush()
    return cand


async def _make_tenant_pos_cand(session, *, tenant_name="T", auto_reject=None, auto_advance=None,
                                 cv_path="cvs/fake.pdf", skills_weight=50, exp_weight=30, edu_weight=20):
    from app.models.tenant import Tenant
    from app.models.user import User
    from app.models.position import Position
    from app.models.candidate import Candidate
    from app.core.security import hash_password

    tenant = Tenant(name=tenant_name, scoring_skills_weight=skills_weight,
                    scoring_experience_weight=exp_weight, scoring_education_weight=edu_weight)
    session.add(tenant)
    await session.flush()
    user = User(tenant_id=tenant.id, email=f"{tenant_name}@t.com", password_hash=hash_password("p"), full_name="U", role="admin")
    session.add(user)
    await session.flush()
    pos = Position(tenant_id=tenant.id, title="Dev", description="D", required_skills=["Python"],
                   seniority_level="mid", created_by=user.id,
                   auto_reject_threshold=auto_reject, auto_advance_threshold=auto_advance)
    session.add(pos)
    await session.flush()
    cand = Candidate(tenant_id=tenant.id, position_id=pos.id, name=f"C_{tenant_name}",
                     email=f"c_{tenant_name}@t.com", cv_file_path=cv_path)
    session.add(cand)
    await session.commit()
    return tenant, user, pos, cand


def _patch_cv_processing(score_response, quality_response=None):
    """Patch Claude + storage for process_cv tests.
    Now process_cv always calls score_cv_quality first, then score_cv per position.
    quality_response defaults to MOCK_CV_QUALITY if not provided.
    score_response is used for the position scoring calls.
    """
    from contextlib import contextmanager
    _quality = quality_response or MOCK_CV_QUALITY

    @contextmanager
    def _ctx():
        # First call = quality scoring, subsequent calls = position scoring
        call_count = {"n": 0}
        def _side_effect(**kw):
            call_count["n"] += 1
            content = kw.get("messages", [{}])[0].get("content", "")
            if "qualite intrinseque" in content:
                return _make_claude_response(_quality)
            return _make_claude_response(score_response)

        with patch("app.workers.cv_processing.get_sync_session", TestSyncSession):
            with patch("anthropic.Anthropic") as mc:
                inst = MagicMock()
                inst.messages.create = MagicMock(side_effect=_side_effect)
                mc.return_value = inst
                with patch("app.services.storage.download_file", return_value=b"%PDF fake"):
                    with patch("app.workers.cv_processing.parse_pdf", return_value=MOCK_CV_PARSED):
                        with patch("app.workers.question_generation.generate_questions.delay"):
                            with patch("app.workers.notifications.send_consent_email.delay"):
                                yield inst
    return _ctx()


# ─── 1. score_cv with position ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_score_cv_with_position():
    from app.workers.cv_processing import score_cv
    pos = MagicMock(title="Dev", description="D", required_skills=["Python"], seniority_level="mid")
    with patch("anthropic.Anthropic") as mc:
        inst = MagicMock()
        inst.messages.create = MagicMock(return_value=_make_claude_response(MOCK_CV_SCORE))
        mc.return_value = inst
        result = score_cv(MOCK_CV_PARSED, pos)
    assert result["score"] == 75
    assert "skills_match" in result["explanation"]
    assert "experience_match" in result["explanation"]
    assert "education_match" in result["explanation"]


# ─── 2. score_cv_quality (vivier) ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_score_cv_vivier_quality():
    from app.workers.cv_processing import score_cv_quality
    with patch("anthropic.Anthropic") as mc:
        inst = MagicMock()
        inst.messages.create = MagicMock(return_value=_make_claude_response(MOCK_CV_QUALITY))
        mc.return_value = inst
        result = score_cv_quality(MOCK_CV_PARSED)
    assert result["score"] == 68
    for k in ("technical_depth", "experience_quality", "education_relevance", "cv_completeness"):
        assert k in result["explanation"]


# ─── 3. Tenant scoring weights ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scoring_weights_from_tenant(_setup_db):
    async with TestSession() as session:
        tenant, user, pos, cand = await _make_tenant_pos_cand(
            session, tenant_name="Weights", skills_weight=60, exp_weight=25, edu_weight=15)
        cand_id = str(cand.id)
    captured = []
    def capture(**kw):
        captured.append(kw.get("messages", [{}])[0].get("content", ""))
        return _make_claude_response(MOCK_CV_PARSED)
    with patch("app.workers.cv_processing.get_sync_session", TestSyncSession):
        with patch("anthropic.Anthropic") as mc:
            inst = MagicMock()
            inst.messages.create = MagicMock(side_effect=capture)
            mc.return_value = inst
            with patch("app.services.storage.download_file", return_value=b"%PDF"):
                with patch("app.workers.cv_processing.parse_pdf", return_value=MOCK_CV_PARSED):
                    from app.workers.cv_processing import process_cv
                    process_cv(cand_id)
    assert any("60" in p for p in captured), "Tenant weight 60 not in prompt"


# ─── 4. Anti-keyword-stuffing ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_anti_keyword_stuffing():
    from app.workers.cv_processing import score_cv
    pos = MagicMock(title="Dev", description="D", required_skills=["Python", "FastAPI"], seniority_level="mid")
    stuffed = {"score": 35, "explanation": {"skills_match": {"score": 30, "matched": [], "missing": ["Python"], "justification": "Liste sans preuves."}, "experience_match": {"score": 35, "justification": "Aucun projet."}, "education_match": {"score": 40, "justification": "OK."}}}
    genuine = {"score": 82, "explanation": {"skills_match": {"score": 85, "matched": ["Python", "FastAPI"], "missing": [], "justification": "Demontrees en projet."}, "experience_match": {"score": 80, "justification": "5 ans."}, "education_match": {"score": 78, "justification": "Master."}}}
    idx = {"n": 0}
    def se(**kw):
        i = idx["n"]; idx["n"] += 1
        return _make_claude_response(stuffed if i == 0 else genuine)
    with patch("anthropic.Anthropic") as mc:
        inst = MagicMock()
        inst.messages.create = MagicMock(side_effect=se)
        mc.return_value = inst
        r1 = score_cv({"skills": ["A"]*20, "experiences": []}, pos)
        r2 = score_cv(MOCK_CV_PARSED, pos)
    assert r1["score"] < r2["score"]
    assert r1["score"] < 50
    assert r2["score"] >= 75


# ─── 5. Auto-reject below threshold ────────────────────────────────────────

@pytest.mark.asyncio
async def test_auto_reject_below_threshold(_setup_db):
    async with TestSession() as session:
        _, _, pos, cand = await _make_tenant_pos_cand(session, tenant_name="Reject", auto_reject=40, auto_advance=80)
        cand_id = cand.id
    low = {"score": 25, "explanation": {"skills_match": {"score": 20, "matched": [], "missing": ["Python"], "justification": "."}, "experience_match": {"score": 25, "justification": "."}, "education_match": {"score": 30, "justification": "."}}}
    with _patch_cv_processing(low):
        from app.workers.cv_processing import process_cv
        process_cv(str(cand_id))
    async with TestSession() as session:
        from app.models.candidate import Candidate
        refreshed = await session.get(Candidate, cand_id)
        assert refreshed.pipeline_status == "rejected"
        assert refreshed.cv_score == 25


# ─── 6. Auto-advance above threshold ───────────────────────────────────────

@pytest.mark.asyncio
async def test_auto_advance_above_threshold(_setup_db):
    async with TestSession() as session:
        _, _, pos, cand = await _make_tenant_pos_cand(session, tenant_name="Advance", auto_reject=30, auto_advance=75)
        cand_id = cand.id
    high = {"score": 88, "explanation": {"skills_match": {"score": 90, "matched": ["Python"], "missing": [], "justification": "."}, "experience_match": {"score": 85, "justification": "."}, "education_match": {"score": 80, "justification": "."}}}
    with _patch_cv_processing(high):
        from app.workers.cv_processing import process_cv
        process_cv(str(cand_id))
    async with TestSession() as session:
        from app.models.candidate import Candidate
        refreshed = await session.get(Candidate, cand_id)
        assert refreshed.pipeline_status == "invited"
        assert refreshed.cv_score == 88


# ─── 7. Borderline score = cv_analyzed ──────────────────────────────────────

@pytest.mark.asyncio
async def test_borderline_score_cv_analyzed(_setup_db):
    async with TestSession() as session:
        _, _, pos, cand = await _make_tenant_pos_cand(session, tenant_name="Border", auto_reject=30, auto_advance=80)
        cand_id = cand.id
    border = {"score": 30, "explanation": {"skills_match": {"score": 30, "matched": [], "missing": [], "justification": "."}, "experience_match": {"score": 30, "justification": "."}, "education_match": {"score": 30, "justification": "."}}}
    with _patch_cv_processing(border):
        from app.workers.cv_processing import process_cv
        process_cv(str(cand_id))
    async with TestSession() as session:
        from app.models.candidate import Candidate
        refreshed = await session.get(Candidate, cand_id)
        assert refreshed.pipeline_status == "cv_analyzed"


# ─── 8. Missing CV skip ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scoring_with_missing_cv(_setup_db):
    async with TestSession() as session:
        _, _, pos, cand = await _make_tenant_pos_cand(session, tenant_name="NoCv", cv_path=None)
        # Override cv_file_path to None
        cand.cv_file_path = None
        await session.commit()
        cand_id = cand.id
    with patch("app.workers.cv_processing.get_sync_session", TestSyncSession):
        with patch("anthropic.Anthropic") as mc:
            inst = MagicMock()
            mc.return_value = inst
            from app.workers.cv_processing import process_cv
            process_cv(str(cand_id))
            inst.messages.create.assert_not_called()
    async with TestSession() as session:
        from app.models.candidate import Candidate
        refreshed = await session.get(Candidate, cand_id)
        assert refreshed.pipeline_status == "new"
        assert refreshed.cv_score is None


# ─── 9. Reprocess CV endpoint ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reprocess_cv_endpoint(client, _setup_db):
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "admin@test.com", "admin")
        cand = await _inject_candidate(session, tenant.id, name="Reprocess", cv_file_path="cvs/f.pdf", cv_parsed_data=MOCK_CV_PARSED)
        await session.commit()
        cand_id = cand.id
    with patch("app.workers.cv_processing.process_cv.delay"):
        res = await client.post(f"/api/v1/candidates/{cand_id}/reprocess-cv", headers=headers)
    assert res.status_code == 200

@pytest.mark.asyncio
async def test_reprocess_cv_not_found(client, _setup_db):
    async with TestSession() as session:
        headers, _, _ = await _create_user(session, "admin@test.com", "admin")
    res = await client.post(f"/api/v1/candidates/{uuid.uuid4()}/reprocess-cv", headers=headers)
    assert res.status_code == 404


# ─── 10-11. Competence dossier PDF + DOCX ──────────────────────────────────

@pytest.mark.asyncio
async def test_competence_dossier_pdf(client, _setup_db):
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "admin@test.com", "admin")
        cand = await _inject_candidate(session, tenant.id, name="DossierPDF", cv_parsed_data=MOCK_CV_PARSED)
        await session.commit()
        cand_id = cand.id
    with patch("app.services.competence_dossier.generate_dossier_pdf", return_value=b"%PDF-fake"):
        res = await client.get(f"/api/v1/candidates/{cand_id}/competence-dossier?format=pdf", headers=headers)
    assert res.status_code == 200
    assert ".pdf" in res.headers.get("content-disposition", "")

@pytest.mark.asyncio
async def test_competence_dossier_docx(client, _setup_db):
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "admin@test.com", "admin")
        cand = await _inject_candidate(session, tenant.id, name="DossierDOCX", cv_parsed_data=MOCK_CV_PARSED)
        await session.commit()
        cand_id = cand.id
    with patch("app.services.competence_dossier.generate_dossier_docx", return_value=b"PK\x03\x04fake"):
        res = await client.get(f"/api/v1/candidates/{cand_id}/competence-dossier?format=docx", headers=headers)
    assert res.status_code == 200
    assert ".docx" in res.headers.get("content-disposition", "")


# ─── 12. Competence dossier errors ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_competence_dossier_no_data(client, _setup_db):
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "admin@test.com", "admin")
        cand = await _inject_candidate(session, tenant.id, name="NoData", cv_parsed_data=None)
        await session.commit()
        cand_id = cand.id
    res = await client.get(f"/api/v1/candidates/{cand_id}/competence-dossier?format=pdf", headers=headers)
    assert res.status_code == 400

@pytest.mark.asyncio
async def test_competence_dossier_parse_error(client, _setup_db):
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "admin@test.com", "admin")
        cand = await _inject_candidate(session, tenant.id, name="ParseErr", cv_parsed_data={"parse_error": True})
        await session.commit()
        cand_id = cand.id
    res = await client.get(f"/api/v1/candidates/{cand_id}/competence-dossier?format=pdf", headers=headers)
    assert res.status_code == 400

@pytest.mark.asyncio
async def test_competence_dossier_invalid_format(client, _setup_db):
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "admin@test.com", "admin")
        cand = await _inject_candidate(session, tenant.id, name="BadFmt", cv_parsed_data=MOCK_CV_PARSED)
        await session.commit()
        cand_id = cand.id
    res = await client.get(f"/api/v1/candidates/{cand_id}/competence-dossier?format=xlsx", headers=headers)
    assert res.status_code == 400


# ─── 13. Export profile fallback ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_export_profile_fallback(client, _setup_db):
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "admin@test.com", "admin")
        cand = await _inject_candidate(session, tenant.id, name="ExportFB", cv_parsed_data=MOCK_CV_PARSED)
        await session.commit()
        cand_id = cand.id
    res = await client.get(f"/api/v1/candidates/{cand_id}/profile/export", headers=headers)
    assert res.status_code == 200

@pytest.mark.asyncio
async def test_export_profile_no_data(client, _setup_db):
    async with TestSession() as session:
        headers, user, tenant = await _create_user(session, "admin@test.com", "admin")
        cand = await _inject_candidate(session, tenant.id, name="ExportNone", cv_parsed_data=None)
        await session.commit()
        cand_id = cand.id
    res = await client.get(f"/api/v1/candidates/{cand_id}/profile/export", headers=headers)
    assert res.status_code == 400


# ─── 14. Error handling ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scoring_claude_exception():
    """score_cv propagates exception when Claude API fails (not caught at this level)."""
    from app.workers.cv_processing import score_cv
    pos = MagicMock(title="D", description="D", required_skills=["P"], seniority_level="m")
    with patch("anthropic.Anthropic") as mc:
        inst = MagicMock()
        inst.messages.create = MagicMock(side_effect=Exception("timeout"))
        mc.return_value = inst
        with pytest.raises(Exception, match="timeout"):
            score_cv(MOCK_CV_PARSED, pos)

@pytest.mark.asyncio
async def test_scoring_bad_json():
    """score_cv returns fallback score=0 when Claude returns non-JSON."""
    from app.workers.cv_processing import score_cv
    pos = MagicMock(title="D", description="D", required_skills=["P"], seniority_level="m")
    bad = MagicMock(); bad.content = [MagicMock(text="Not JSON")]; bad.stop_reason = "end_turn"
    with patch("anthropic.Anthropic") as mc:
        inst = MagicMock()
        inst.messages.create = MagicMock(return_value=bad)
        mc.return_value = inst
        result = score_cv(MOCK_CV_PARSED, pos)
    assert result["score"] == 0

@pytest.mark.asyncio
async def test_quality_scoring_exception():
    """score_cv_quality propagates exception when Claude API fails."""
    from app.workers.cv_processing import score_cv_quality
    with patch("anthropic.Anthropic") as mc:
        inst = MagicMock()
        inst.messages.create = MagicMock(side_effect=Exception("err"))
        mc.return_value = inst
        with pytest.raises(Exception, match="err"):
            score_cv_quality(MOCK_CV_PARSED)


# ─── 15. Vivier full pipeline ───────────────────────────────────────────────

def test_vivier_full_pipeline():
    """Test vivier pipeline entirely mocked (no DB needed)."""
    import uuid
    cand = MagicMock()
    cand.id = uuid.uuid4()
    cand.cv_file_path = "cvs/v.pdf"
    cand.position_id = None
    cand.tenant_id = uuid.uuid4()
    cand.cv_parsed_data = {}
    cand.cv_score = None
    cand.cv_score_explanation = None
    cand.profile_score = None
    cand.profile_score_explanation = None
    cand.pipeline_status = "new"

    tenant = MagicMock()
    tenant.scoring_skills_weight = 50
    tenant.scoring_experience_weight = 30
    tenant.scoring_education_weight = 20

    sess = MagicMock()
    def _get(model, uid):
        name = model.__name__
        if name == "Candidate": return cand
        if name == "Tenant": return tenant
        return None
    sess.get.side_effect = _get
    # Mock query().filter().all() for Application lookup — vivier has no applications
    sess.query.return_value.filter.return_value.all.return_value = []

    with patch("app.workers.cv_processing.get_sync_session", return_value=sess), \
         patch("app.workers.cv_processing.parse_cv_file", return_value=MOCK_CV_PARSED):
        from app.workers.cv_processing import process_cv
        process_cv(str(cand.id))
    assert cand.pipeline_status == "cv_analyzed"
    assert cand.profile_score == 68
    assert cand.cv_score == 68  # vivier: cv_score = profile_score for compat


# ─── 16. Default weights ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_default_weights():
    from app.workers.cv_processing import score_cv
    pos = MagicMock(title="D", description="D", required_skills=["P"], seniority_level="m")
    captured = []
    def cap(**kw):
        captured.append(kw)
        return _make_claude_response(MOCK_CV_SCORE)
    with patch("anthropic.Anthropic") as mc:
        inst = MagicMock()
        inst.messages.create = MagicMock(side_effect=cap)
        mc.return_value = inst
        score_cv(MOCK_CV_PARSED, pos, weights=None)
    prompt = captured[0]["messages"][0]["content"]
    assert "50" in prompt and "30" in prompt and "20" in prompt


# ─── 17. Double scoring: profile + position via Applications ──────────────

@pytest.mark.asyncio
async def test_double_scoring_with_applications(_setup_db):
    """process_cv computes profile_score AND match_score per Application."""
    from app.models.application import Application

    async with TestSession() as session:
        tenant, user, pos, cand = await _make_tenant_pos_cand(
            session, tenant_name="DblScore")
        # Create an Application linking candidate to position
        app = Application(
            tenant_id=tenant.id,
            candidate_id=cand.id,
            position_id=pos.id,
            pipeline_status="new",
        )
        session.add(app)
        await session.commit()
        cand_id = cand.id
        app_id = app.id

    with _patch_cv_processing(MOCK_CV_SCORE):
        from app.workers.cv_processing import process_cv
        process_cv(str(cand_id))

    async with TestSession() as session:
        from app.models.candidate import Candidate
        refreshed = await session.get(Candidate, cand_id)
        assert refreshed.profile_score is not None, "profile_score should be set"
        assert refreshed.profile_score == 68  # MOCK_CV_QUALITY score
        assert refreshed.cv_score == 75  # MOCK_CV_SCORE from position scoring
        assert refreshed.pipeline_status == "cv_analyzed"

        refreshed_app = await session.get(Application, app_id)
        assert refreshed_app.match_score == 75  # MOCK_CV_SCORE


# ─── 18. Profile score always computed even with position ─────────────────

@pytest.mark.asyncio
async def test_profile_score_always_computed(_setup_db):
    """profile_score is set even for candidates linked to a position (legacy path)."""
    async with TestSession() as session:
        _, _, pos, cand = await _make_tenant_pos_cand(
            session, tenant_name="AlwaysProfile")
        cand_id = cand.id

    with _patch_cv_processing(MOCK_CV_SCORE):
        from app.workers.cv_processing import process_cv
        process_cv(str(cand_id))

    async with TestSession() as session:
        from app.models.candidate import Candidate
        refreshed = await session.get(Candidate, cand_id)
        assert refreshed.profile_score == 68  # Always computed
        assert refreshed.cv_score == 75  # From position scoring (legacy path)


# ─── 19. Multiple applications score each position ───────────────────────

@pytest.mark.asyncio
async def test_multi_position_scoring(_setup_db):
    """When candidate has multiple Applications, each gets its own match_score."""
    from app.models.application import Application
    from app.models.position import Position as PositionModel
    from app.core.security import hash_password

    async with TestSession() as session:
        from app.models.tenant import Tenant
        from app.models.user import User

        tenant = Tenant(name="MultiPos", scoring_skills_weight=50,
                        scoring_experience_weight=30, scoring_education_weight=20)
        session.add(tenant)
        await session.flush()
        user = User(tenant_id=tenant.id, email="multi@t.com",
                    password_hash=hash_password("p"), full_name="U", role="admin")
        session.add(user)
        await session.flush()

        pos1 = PositionModel(tenant_id=tenant.id, title="Dev Python",
                             description="Backend", required_skills=["Python"],
                             seniority_level="mid", created_by=user.id)
        pos2 = PositionModel(tenant_id=tenant.id, title="Dev React",
                             description="Frontend", required_skills=["React"],
                             seniority_level="mid", created_by=user.id)
        session.add_all([pos1, pos2])
        await session.flush()

        from app.models.candidate import Candidate
        cand = Candidate(tenant_id=tenant.id, position_id=pos1.id,
                         name="MultiApp", email="multi@c.com",
                         cv_file_path="cvs/multi.pdf")
        session.add(cand)
        await session.flush()

        app1 = Application(tenant_id=tenant.id, candidate_id=cand.id,
                           position_id=pos1.id, pipeline_status="new")
        app2 = Application(tenant_id=tenant.id, candidate_id=cand.id,
                           position_id=pos2.id, pipeline_status="new")
        session.add_all([app1, app2])
        await session.commit()
        cand_id, app1_id, app2_id = cand.id, app1.id, app2.id

    with _patch_cv_processing(MOCK_CV_SCORE):
        from app.workers.cv_processing import process_cv
        process_cv(str(cand_id))

    async with TestSession() as session:
        refreshed_app1 = await session.get(Application, app1_id)
        refreshed_app2 = await session.get(Application, app2_id)
        assert refreshed_app1.match_score == 75
        assert refreshed_app2.match_score == 75
        from app.models.candidate import Candidate
        refreshed = await session.get(Candidate, cand_id)
        assert refreshed.profile_score == 68
        assert refreshed.cv_score == 75  # primary position score
