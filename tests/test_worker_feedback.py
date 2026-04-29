"""Tests for feedback worker — trigger logic and worker execution."""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


def _make_candidate(email="jean@test.com"):
    c = MagicMock()
    c.id = uuid.uuid4()
    c.name = "Jean Dupont"
    c.email = email
    c.cv_parsed_data = {"skills": ["Python"], "experience_years": 5}
    c.cv_score = 72.0
    c.profile_score = 75.0
    c.feedback_json = None
    c.feedback_sent_at = None
    return c


def _make_interview(candidate_id=None, position_id=None):
    i = MagicMock()
    i.id = uuid.uuid4()
    i.candidate_id = candidate_id or uuid.uuid4()
    i.position_id = position_id or uuid.uuid4()
    i.tenant_id = uuid.uuid4()
    i.analysis_json = None
    return i


def _make_position():
    p = MagicMock()
    p.id = uuid.uuid4()
    p.title = "Developpeur Python"
    p.required_skills = ["Python", "FastAPI"]
    return p


def _make_consent(granted=True):
    c = MagicMock()
    c.granted = granted
    return c


SAMPLE_FEEDBACK = {
    "greeting": "Bonjour Jean,",
    "strengths": [{"title": "Python", "detail": "5 ans"}],
    "improvements": [{"title": "Cloud", "detail": "A explorer", "advice": "Certif AWS"}],
    "general_advice": "Continuez a progresser.",
    "closing": "Bonne continuation.",
    "generated_at": "2026-04-10T12:00:00+00:00",
}


class TestFeedbackTriggerInReportGeneration:
    """Test that report_generation triggers feedback when consent exists."""

    def _setup_report_session(self, interview, candidate, position, analysis=None, transcription=None, consent=None):
        """Setup mock session for report generation with consent check."""
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

        # execute() calls: Analysis, Transcription, then Consent
        mock_analysis_result = MagicMock()
        mock_analysis_result.scalar_one_or_none.return_value = analysis
        mock_trans_result = MagicMock()
        mock_trans_result.scalar_one_or_none.return_value = transcription
        mock_consent_result = MagicMock()
        mock_consent_result.scalar_one_or_none.return_value = consent

        session.execute.side_effect = [mock_analysis_result, mock_trans_result, mock_consent_result]
        return session

    @patch("app.workers.report_generation._cleanup_audio")
    @patch("app.workers.report_generation._generate_and_upload_pdf")
    @patch("app.workers.base.get_sync_session")
    def test_feedback_triggered_on_consent(self, mock_get_session, mock_pdf, mock_cleanup):
        from app.workers.report_generation import generate_report

        candidate = _make_candidate()
        position = _make_position()
        interview = _make_interview(candidate_id=candidate.id, position_id=position.id)
        consent = _make_consent(granted=True)

        session = self._setup_report_session(interview, candidate, position, consent=consent)
        mock_get_session.return_value = session
        mock_pdf.return_value = "reports-bucket/test.pdf"

        valid_report = '{"title":"Test","scores":{"global":78},"metadata":{}}'

        with patch("app.core.config.get_settings") as mock_settings, \
             patch("anthropic.Anthropic") as mock_anthropic_cls, \
             patch("app.workers.notifications.send_report_ready") as mock_notif, \
             patch("app.workers.feedback.generate_and_send_feedback") as mock_feedback:
            mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
            mock_msg = MagicMock()
            mock_msg.content = [MagicMock(text=valid_report)]
            mock_anthropic_cls.return_value.messages.create.return_value = mock_msg
            mock_notif.delay = MagicMock()
            mock_feedback.delay = MagicMock()

            generate_report(str(interview.id))

            mock_feedback.delay.assert_called_once_with(str(candidate.id), str(interview.id))

    @patch("app.workers.report_generation._cleanup_audio")
    @patch("app.workers.report_generation._generate_and_upload_pdf")
    @patch("app.workers.base.get_sync_session")
    def test_feedback_skipped_without_consent(self, mock_get_session, mock_pdf, mock_cleanup):
        from app.workers.report_generation import generate_report

        candidate = _make_candidate()
        position = _make_position()
        interview = _make_interview(candidate_id=candidate.id, position_id=position.id)

        session = self._setup_report_session(interview, candidate, position, consent=None)
        mock_get_session.return_value = session
        mock_pdf.return_value = "reports-bucket/test.pdf"

        valid_report = '{"title":"Test","scores":{"global":78},"metadata":{}}'

        with patch("app.core.config.get_settings") as mock_settings, \
             patch("anthropic.Anthropic") as mock_anthropic_cls, \
             patch("app.workers.notifications.send_report_ready") as mock_notif, \
             patch("app.workers.feedback.generate_and_send_feedback") as mock_feedback:
            mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
            mock_msg = MagicMock()
            mock_msg.content = [MagicMock(text=valid_report)]
            mock_anthropic_cls.return_value.messages.create.return_value = mock_msg
            mock_notif.delay = MagicMock()
            mock_feedback.delay = MagicMock()

            generate_report(str(interview.id))

            mock_feedback.delay.assert_not_called()


class TestGenerateAndSendFeedback:
    """Test the feedback worker itself."""

    @patch("app.workers.base.get_sync_session")
    def test_stores_feedback_in_db(self, mock_get_session):
        from app.workers.feedback import generate_and_send_feedback

        candidate = _make_candidate()
        position = _make_position()
        interview = _make_interview(candidate_id=candidate.id, position_id=position.id)

        session = MagicMock()
        mock_get_session.return_value = session

        def get_side_effect(model_cls, uid):
            name = model_cls.__name__
            if name == "Candidate":
                return candidate
            if name == "Interview":
                return interview
            if name == "Position":
                return position
            return None

        session.get.side_effect = get_side_effect

        # No analysis_json on interview, so it queries Analysis table
        mock_analysis_result = MagicMock()
        mock_analysis_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_analysis_result

        with patch("app.services.candidate_feedback.generate_candidate_feedback") as mock_gen, \
             patch("app.workers.notifications.send_email") as mock_email:
            mock_gen.return_value = SAMPLE_FEEDBACK
            mock_email.delay = MagicMock()

            generate_and_send_feedback(str(candidate.id), str(interview.id))

        assert candidate.feedback_json == SAMPLE_FEEDBACK
        assert candidate.feedback_sent_at is not None
        session.commit.assert_called_once()
        mock_email.delay.assert_called_once()

    @patch("app.workers.base.get_sync_session")
    def test_no_email_if_candidate_has_no_email(self, mock_get_session):
        from app.workers.feedback import generate_and_send_feedback

        candidate = _make_candidate(email=None)
        position = _make_position()
        interview = _make_interview(candidate_id=candidate.id, position_id=position.id)

        session = MagicMock()
        mock_get_session.return_value = session

        def get_side_effect(model_cls, uid):
            name = model_cls.__name__
            if name == "Candidate":
                return candidate
            if name == "Interview":
                return interview
            if name == "Position":
                return position
            return None

        session.get.side_effect = get_side_effect
        mock_analysis_result = MagicMock()
        mock_analysis_result.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_analysis_result

        with patch("app.services.candidate_feedback.generate_candidate_feedback") as mock_gen, \
             patch("app.workers.notifications.send_email") as mock_email:
            mock_gen.return_value = SAMPLE_FEEDBACK
            mock_email.delay = MagicMock()

            generate_and_send_feedback(str(candidate.id), str(interview.id))

        assert candidate.feedback_json == SAMPLE_FEEDBACK
        mock_email.delay.assert_not_called()

    @patch("app.workers.base.get_sync_session")
    def test_candidate_not_found(self, mock_get_session):
        from app.workers.feedback import generate_and_send_feedback

        session = MagicMock()
        mock_get_session.return_value = session
        session.get.return_value = None

        generate_and_send_feedback(str(uuid.uuid4()), str(uuid.uuid4()))
        session.commit.assert_not_called()
