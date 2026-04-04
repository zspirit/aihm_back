import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


def _make_position(required_skills=None):
    p = MagicMock()
    p.title = "Developpeur Python"
    p.description = "Poste de dev Python senior."
    p.seniority_level = "senior"
    p.required_skills = required_skills or ["Python", "FastAPI"]
    return p


def _make_candidate(cv_data=None):
    c = MagicMock()
    c.id = uuid.uuid4()
    c.name = "Jean Dupont"
    c.cv_parsed_data = cv_data or {"skills": ["Python"]}
    c.pipeline_status = "interviewed"
    return c


def _make_interview(candidate_id=None, position_id=None, tenant_id=None):
    i = MagicMock()
    i.id = uuid.uuid4()
    i.candidate_id = candidate_id or uuid.uuid4()
    i.position_id = position_id or uuid.uuid4()
    i.tenant_id = tenant_id or uuid.uuid4()
    i.duration_seconds = 300
    i.ended_at = datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc)
    i.created_at = datetime(2026, 3, 15, 9, 55, tzinfo=timezone.utc)
    i.questions_asked = [{"id": 1, "text": "Question 1"}]
    i.audio_file_path = "audio-bucket/test-audio.wav"
    return i


def _make_transcription(full_text=None):
    t = MagicMock()
    t.full_text = full_text or "Q: Parlez-moi de votre experience. R: J'ai 5 ans d'experience Python."
    t.segments = {"q1": "experience Python"}
    t.interview_id = uuid.uuid4()
    return t


def _make_analysis(scores=None, skill_scores=None):
    a = MagicMock()
    a.scores = scores or {"technical": 80, "experience": 75, "communication": 78, "global": 78}
    a.score_explanations = {"technical": "bon", "experience": "bon", "communication": "bon", "global": "bon"}
    a.skills_extracted = [{"skill": "Python", "evidence": "5 ans"}]
    a.experience_examples = [{"situation": "projet", "task": "dev", "action": "code", "result": "ok"}]
    a.communication_indicators = {"clarity": {"score": 80}, "structure": {"score": 75}}
    a.skill_scores = skill_scores
    return a


VALID_REPORT = {
    "title": "Rapport d'evaluation - Jean Dupont",
    "position": "Developpeur Python",
    "date": "2026-03-15",
    "summary": "Le candidat presente un profil solide avec un score global de 78/100.",
    "scores": {"global": 78, "technical": 80, "experience": 75, "communication": 78},
    "strengths": ["Maitrise de Python demontree via un projet de pipeline"],
    "areas_to_explore": ["Comment gerez-vous la priorisation de projets concurrents ?"],
    "skills_assessment": [{"skill": "Python", "level": "avance", "evidence": "5 ans"}],
    "key_quotes": ["J'ai 5 ans d'experience Python."],
    "metadata": {
        "interview_duration": "300s",
        "questions_count": 1,
        "generated_by": "AIHM AI Assistant",
        "disclaimer": "Ce rapport est genere par IA.",
    },
}
VALID_REPORT_JSON = json.dumps(VALID_REPORT)


# ── Helper functions ──────────────────────────────────────────────

class TestComputeMatchingScore:
    def test_empty_skill_scores(self):
        from app.workers.report_generation import _compute_matching_score

        assert _compute_matching_score([], None) == 0
        assert _compute_matching_score(None, None) == 0

    def test_basic_matching(self):
        from app.workers.report_generation import _compute_matching_score

        skill_scores = [
            {"skill": "Python", "level_required": 4, "demonstrated": 4},
            {"skill": "SQL", "level_required": 3, "demonstrated": 3},
        ]
        result = _compute_matching_score(skill_scores, None)
        assert result == 100  # both at 100%

    def test_partial_matching(self):
        from app.workers.report_generation import _compute_matching_score

        skill_scores = [
            {"skill": "Python", "level_required": 4, "demonstrated": 2},
        ]
        result = _compute_matching_score(skill_scores, None)
        assert result == 50

    def test_weighted_matching(self):
        from app.workers.report_generation import _compute_matching_score

        skill_scores = [
            {"skill": "Python", "level_required": 4, "demonstrated": 4},
            {"skill": "SQL", "level_required": 4, "demonstrated": 0},
        ]
        required_skills = [
            {"name": "Python", "weight": 3},
            {"name": "SQL", "weight": 1},
        ]
        result = _compute_matching_score(skill_scores, required_skills)
        # Python: 1.0 * 3 = 3, SQL: 0.0 * 1 = 0, total = 3/4 = 75
        assert result == 75

    def test_over_demonstrated_capped(self):
        from app.workers.report_generation import _compute_matching_score

        skill_scores = [{"skill": "Python", "level_required": 3, "demonstrated": 5}]
        result = _compute_matching_score(skill_scores, None)
        assert result == 100  # capped at 1.0

    def test_zero_required(self):
        from app.workers.report_generation import _compute_matching_score

        skill_scores = [{"skill": "Python", "level_required": 0, "demonstrated": 3}]
        result = _compute_matching_score(skill_scores, None)
        assert result == 100


class TestBuildSkillMatrixForPrompt:
    def test_empty(self):
        from app.workers.report_generation import _build_skill_matrix_for_prompt

        result = _build_skill_matrix_for_prompt(None)
        assert "Aucune donnee" in result
        result2 = _build_skill_matrix_for_prompt([])
        assert "Aucune donnee" in result2

    def test_with_scores(self):
        from app.workers.report_generation import _build_skill_matrix_for_prompt

        skill_scores = [
            {"skill": "Python", "category": "backend", "level_required": 4,
             "demonstrated": 3, "motivation": 4, "evidence": "5 ans de pratique"},
        ]
        result = _build_skill_matrix_for_prompt(skill_scores)
        assert "Python" in result
        assert "backend" in result
        assert "requis=4/5" in result
        assert "demontre=3/5" in result


# ── build_report (unit function) ─────────────────────────────────

class TestBuildReport:
    @patch("app.core.config.get_settings")
    @patch("anthropic.Anthropic")
    def test_happy_path(self, mock_anthropic_cls, mock_settings):
        from app.workers.report_generation import build_report

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=VALID_REPORT_JSON)]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        result = build_report(
            _make_candidate(), _make_position(), _make_interview(),
            _make_analysis(), _make_transcription(),
        )

        assert result["title"] == "Rapport d'evaluation - Jean Dupont"
        assert result["scores"]["global"] == 78
        mock_anthropic_cls.return_value.messages.create.assert_called_once()

    @patch("app.core.config.get_settings")
    @patch("anthropic.Anthropic")
    def test_json_in_code_block(self, mock_anthropic_cls, mock_settings):
        from app.workers.report_generation import build_report

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=f"```json\n{VALID_REPORT_JSON}\n```")]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        result = build_report(
            _make_candidate(), _make_position(), _make_interview(),
            _make_analysis(), _make_transcription(),
        )
        assert result["scores"]["global"] == 78

    @patch("app.core.config.get_settings")
    @patch("anthropic.Anthropic")
    def test_invalid_json_fallback(self, mock_anthropic_cls, mock_settings):
        from app.workers.report_generation import build_report

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="not valid json")]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        candidate = _make_candidate()
        position = _make_position()
        analysis = _make_analysis()

        result = build_report(candidate, position, _make_interview(), analysis, _make_transcription())

        assert result["title"] == f"Rapport - {candidate.name}"
        assert result["metadata"]["error"] is True
        assert result["scores"] == analysis.scores

    @patch("app.core.config.get_settings")
    @patch("anthropic.Anthropic")
    def test_no_analysis(self, mock_anthropic_cls, mock_settings):
        from app.workers.report_generation import build_report

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=VALID_REPORT_JSON)]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        result = build_report(
            _make_candidate(), _make_position(), _make_interview(),
            None, _make_transcription(),
        )
        assert result["scores"]["global"] == 78

    @patch("app.core.config.get_settings")
    @patch("anthropic.Anthropic")
    def test_no_transcription(self, mock_anthropic_cls, mock_settings):
        from app.workers.report_generation import build_report

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=VALID_REPORT_JSON)]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        result = build_report(
            _make_candidate(), _make_position(), _make_interview(),
            _make_analysis(), None,
        )
        assert "title" in result

    @patch("app.core.config.get_settings")
    @patch("anthropic.Anthropic")
    def test_with_skill_scores_matching(self, mock_anthropic_cls, mock_settings):
        from app.workers.report_generation import build_report

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
        # Return a report WITHOUT skill_matrix to trigger the fallback injection
        report_no_matrix = {**VALID_REPORT}
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=json.dumps(report_no_matrix))]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        skill_scores = [
            {"skill": "Python", "category": "backend", "level_required": 4,
             "demonstrated": 4, "motivation": 3, "evidence": "5 ans"},
        ]
        analysis = _make_analysis(skill_scores=skill_scores)
        position = _make_position(required_skills=[{"name": "Python", "weight": 3}])

        result = build_report(_make_candidate(), position, _make_interview(), analysis, _make_transcription())

        assert "matching_score" in result
        assert result["matching_score"] == 100
        assert "skill_matrix" in result
        assert result["skill_matrix"][0]["skill"] == "Python"

    @patch("app.core.config.get_settings")
    @patch("anthropic.Anthropic")
    def test_fallback_includes_skill_matrix(self, mock_anthropic_cls, mock_settings):
        from app.workers.report_generation import build_report

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="invalid json")]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        skill_scores = [
            {"skill": "Python", "category": "backend", "level_required": 4,
             "demonstrated": 3, "motivation": 4, "evidence": "bonne maitrise"},
        ]
        analysis = _make_analysis(skill_scores=skill_scores)

        result = build_report(
            _make_candidate(), _make_position(), _make_interview(),
            analysis, _make_transcription(),
        )

        assert result["metadata"]["error"] is True
        assert "skill_matrix" in result
        assert result["skill_matrix"][0]["skill"] == "Python"
        assert "matching_score" in result


# ── _generate_and_upload_pdf ─────────────────────────────────────

class TestGenerateAndUploadPdf:
    @patch("app.services.storage.ensure_bucket")
    @patch("app.services.storage.s3_client")
    @patch("app.services.pdf_report.generate_pdf")
    @patch("app.core.config.get_settings")
    def test_happy_path(self, mock_settings, mock_gen_pdf, mock_s3, mock_ensure):
        from app.workers.report_generation import _generate_and_upload_pdf

        mock_settings.return_value = MagicMock(S3_BUCKET_REPORTS="reports-bucket")
        mock_gen_pdf.return_value = b"%PDF-fake-content"

        result = _generate_and_upload_pdf(VALID_REPORT, "interview-123")

        assert result == "reports-bucket/interview-123.pdf"
        mock_ensure.assert_called_once_with("reports-bucket")
        mock_s3.put_object.assert_called_once()
        put_kwargs = mock_s3.put_object.call_args[1]
        assert put_kwargs["Bucket"] == "reports-bucket"
        assert put_kwargs["Key"] == "interview-123.pdf"
        assert put_kwargs["ContentType"] == "application/pdf"

    @patch("app.services.pdf_report.generate_pdf")
    @patch("app.core.config.get_settings")
    def test_pdf_error_returns_none(self, mock_settings, mock_gen_pdf):
        from app.workers.report_generation import _generate_and_upload_pdf

        mock_settings.return_value = MagicMock(S3_BUCKET_REPORTS="reports-bucket")
        mock_gen_pdf.side_effect = RuntimeError("PDF generation failed")

        result = _generate_and_upload_pdf(VALID_REPORT, "interview-123")
        assert result is None

    @patch("app.services.storage.ensure_bucket")
    @patch("app.services.storage.s3_client")
    @patch("app.services.pdf_report.generate_pdf")
    @patch("app.core.config.get_settings")
    def test_s3_upload_error_returns_none(self, mock_settings, mock_gen_pdf, mock_s3, mock_ensure):
        from app.workers.report_generation import _generate_and_upload_pdf

        mock_settings.return_value = MagicMock(S3_BUCKET_REPORTS="reports-bucket")
        mock_gen_pdf.return_value = b"%PDF-fake"
        mock_s3.put_object.side_effect = RuntimeError("S3 down")

        result = _generate_and_upload_pdf(VALID_REPORT, "interview-123")
        assert result is None


# ── _cleanup_audio ───────────────────────────────────────────────

class TestCleanupAudio:
    def test_no_audio_path(self):
        from app.workers.report_generation import _cleanup_audio

        interview = MagicMock()
        interview.audio_file_path = None
        _cleanup_audio(interview)  # should not raise

    @patch("app.services.storage.delete_file")
    def test_cleanup_success(self, mock_delete):
        from app.workers.report_generation import _cleanup_audio

        interview = MagicMock()
        interview.audio_file_path = "audio-bucket/test.wav"
        _cleanup_audio(interview)
        mock_delete.assert_called_once_with("audio-bucket/test.wav")

    @patch("app.services.storage.delete_file")
    def test_cleanup_error_no_raise(self, mock_delete):
        from app.workers.report_generation import _cleanup_audio

        mock_delete.side_effect = RuntimeError("S3 error")
        interview = MagicMock()
        interview.audio_file_path = "audio-bucket/test.wav"
        _cleanup_audio(interview)  # should not raise


# ── generate_report Celery task ──────────────────────────────────

class TestGenerateReportTask:
    def _setup_session(self, interview, candidate, position, analysis=None, transcription=None):
        session = MagicMock()

        def get_side_effect(model_cls, uid):
            name = model_cls.__name__
            if name == "Interview":
                return interview
            if name == "Candidate":
                return candidate
            if name == "Position":
                return position
            return None

        session.get.side_effect = get_side_effect

        # execute() is called twice: once for Analysis, once for Transcription
        mock_analysis_result = MagicMock()
        mock_analysis_result.scalar_one_or_none.return_value = analysis
        mock_trans_result = MagicMock()
        mock_trans_result.scalar_one_or_none.return_value = transcription
        session.execute.side_effect = [mock_analysis_result, mock_trans_result]

        return session

    @patch("app.workers.report_generation._cleanup_audio")
    @patch("app.workers.report_generation._generate_and_upload_pdf")
    @patch("app.workers.base.get_sync_session")
    def test_happy_path(self, mock_get_session, mock_pdf, mock_cleanup):
        from app.workers.report_generation import generate_report

        candidate = _make_candidate()
        position = _make_position()
        interview = _make_interview(candidate_id=candidate.id, position_id=position.id)
        analysis = _make_analysis()
        transcription = _make_transcription()

        session = self._setup_session(interview, candidate, position, analysis, transcription)
        mock_get_session.return_value = session
        mock_pdf.return_value = "reports-bucket/test.pdf"

        with patch("app.core.config.get_settings") as mock_settings, \
             patch("anthropic.Anthropic") as mock_anthropic_cls, \
             patch("app.workers.notifications.send_report_ready") as mock_notif:
            mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
            mock_msg = MagicMock()
            mock_msg.content = [MagicMock(text=VALID_REPORT_JSON)]
            mock_anthropic_cls.return_value.messages.create.return_value = mock_msg
            mock_notif.delay = MagicMock()

            generate_report(str(interview.id))

        session.add.assert_called_once()
        session.commit.assert_called_once()
        mock_cleanup.assert_called_once_with(interview)
        mock_notif.delay.assert_called_once_with(str(interview.id))

    @patch("app.workers.base.get_sync_session")
    def test_interview_not_found(self, mock_get_session):
        from app.workers.report_generation import generate_report

        session = MagicMock()
        mock_get_session.return_value = session
        session.get.return_value = None

        result = generate_report(str(uuid.uuid4()))
        assert result is None
        session.commit.assert_not_called()

    @patch("app.workers.base.get_sync_session")
    def test_candidate_not_found(self, mock_get_session):
        from app.workers.report_generation import generate_report

        interview = _make_interview()
        session = MagicMock()
        mock_get_session.return_value = session

        def get_side_effect(model_cls, uid):
            name = model_cls.__name__
            if name == "Interview":
                return interview
            return None

        session.get.side_effect = get_side_effect

        result = generate_report(str(uuid.uuid4()))
        assert result is None
        session.commit.assert_not_called()

    @patch("app.workers.base.get_sync_session")
    def test_position_not_found(self, mock_get_session):
        from app.workers.report_generation import generate_report

        interview = _make_interview()
        candidate = _make_candidate()
        session = MagicMock()
        mock_get_session.return_value = session

        def get_side_effect(model_cls, uid):
            name = model_cls.__name__
            if name == "Interview":
                return interview
            if name == "Candidate":
                return candidate
            return None

        session.get.side_effect = get_side_effect

        result = generate_report(str(uuid.uuid4()))
        assert result is None
        session.commit.assert_not_called()

    @patch("app.workers.report_generation._cleanup_audio")
    @patch("app.workers.report_generation._generate_and_upload_pdf")
    @patch("app.workers.base.get_sync_session")
    def test_no_analysis_no_transcription(self, mock_get_session, mock_pdf, mock_cleanup):
        from app.workers.report_generation import generate_report

        candidate = _make_candidate()
        position = _make_position()
        interview = _make_interview(candidate_id=candidate.id, position_id=position.id)

        session = self._setup_session(interview, candidate, position, None, None)
        mock_get_session.return_value = session
        mock_pdf.return_value = None  # PDF fails too

        with patch("app.core.config.get_settings") as mock_settings, \
             patch("anthropic.Anthropic") as mock_anthropic_cls, \
             patch("app.workers.notifications.send_report_ready") as mock_notif:
            mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
            mock_msg = MagicMock()
            mock_msg.content = [MagicMock(text=VALID_REPORT_JSON)]
            mock_anthropic_cls.return_value.messages.create.return_value = mock_msg
            mock_notif.delay = MagicMock()

            generate_report(str(interview.id))

        session.add.assert_called_once()
        session.commit.assert_called_once()

    @patch("app.workers.report_generation._cleanup_audio")
    @patch("app.workers.report_generation._generate_and_upload_pdf")
    @patch("app.workers.base.get_sync_session")
    def test_pdf_failure_still_saves_report(self, mock_get_session, mock_pdf, mock_cleanup):
        from app.workers.report_generation import generate_report

        candidate = _make_candidate()
        position = _make_position()
        interview = _make_interview(candidate_id=candidate.id, position_id=position.id)
        analysis = _make_analysis()
        transcription = _make_transcription()

        session = self._setup_session(interview, candidate, position, analysis, transcription)
        mock_get_session.return_value = session
        mock_pdf.return_value = None  # PDF generation fails

        with patch("app.core.config.get_settings") as mock_settings, \
             patch("anthropic.Anthropic") as mock_anthropic_cls, \
             patch("app.workers.notifications.send_report_ready") as mock_notif:
            mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
            mock_msg = MagicMock()
            mock_msg.content = [MagicMock(text=VALID_REPORT_JSON)]
            mock_anthropic_cls.return_value.messages.create.return_value = mock_msg
            mock_notif.delay = MagicMock()

            generate_report(str(interview.id))

        # Report is still saved even without PDF
        session.add.assert_called_once()
        session.commit.assert_called_once()
        # Check the Report object has pdf_file_path=None
        report_obj = session.add.call_args[0][0]
        assert report_obj.pdf_file_path is None

    @patch("app.workers.base.get_sync_session")
    def test_claude_error_retries(self, mock_get_session):
        from app.workers.report_generation import generate_report

        candidate = _make_candidate()
        position = _make_position()
        interview = _make_interview(candidate_id=candidate.id, position_id=position.id)
        analysis = _make_analysis()
        transcription = _make_transcription()

        session = self._setup_session(interview, candidate, position, analysis, transcription)
        mock_get_session.return_value = session

        with patch("app.core.config.get_settings") as mock_settings, \
             patch("anthropic.Anthropic") as mock_anthropic_cls:
            mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
            mock_anthropic_cls.return_value.messages.create.side_effect = RuntimeError("Claude API down")

            with pytest.raises(RuntimeError):
                generate_report(str(interview.id))

        session.rollback.assert_called_once()
        session.close.assert_called_once()

    @patch("app.workers.report_generation._cleanup_audio")
    @patch("app.workers.report_generation._generate_and_upload_pdf")
    @patch("app.workers.base.get_sync_session")
    def test_notification_failure_non_blocking(self, mock_get_session, mock_pdf, mock_cleanup):
        from app.workers.report_generation import generate_report

        candidate = _make_candidate()
        position = _make_position()
        interview = _make_interview(candidate_id=candidate.id, position_id=position.id)
        analysis = _make_analysis()
        transcription = _make_transcription()

        session = self._setup_session(interview, candidate, position, analysis, transcription)
        mock_get_session.return_value = session
        mock_pdf.return_value = "reports-bucket/test.pdf"

        with patch("app.core.config.get_settings") as mock_settings, \
             patch("anthropic.Anthropic") as mock_anthropic_cls, \
             patch("app.workers.notifications.send_report_ready") as mock_notif:
            mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
            mock_msg = MagicMock()
            mock_msg.content = [MagicMock(text=VALID_REPORT_JSON)]
            mock_anthropic_cls.return_value.messages.create.return_value = mock_msg
            mock_notif.delay.side_effect = RuntimeError("Email service down")

            # Should NOT raise despite notification failure
            generate_report(str(interview.id))

        session.add.assert_called_once()
        session.commit.assert_called_once()
