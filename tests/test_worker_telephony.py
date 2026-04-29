import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


def _make_candidate(phone="+212600000000"):
    c = MagicMock()
    c.id = uuid.uuid4()
    c.phone = phone
    c.pipeline_status = "consented"
    return c


def _make_position():
    p = MagicMock()
    p.id = uuid.uuid4()
    p.title = "Dev Python"
    p.required_skills = ["Python", "FastAPI"]
    return p


def _make_interview(candidate_id=None, position_id=None, tenant_id=None):
    i = MagicMock()
    i.id = uuid.uuid4()
    i.candidate_id = candidate_id or uuid.uuid4()
    i.position_id = position_id or uuid.uuid4()
    i.tenant_id = tenant_id or uuid.uuid4()
    i.status = "scheduled"
    i.call_provider_id = None
    i.started_at = None
    i.questions_asked = None
    i.audio_file_path = None
    i.ended_at = None
    i.duration_seconds = None
    return i


class TestInitiateCall:
    def _setup_session(self, interview, candidate, position):
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
        return session

    @patch("app.workers.base.get_sync_session")
    def test_interview_not_found(self, mock_get_session):
        from app.workers.telephony import initiate_call

        session = MagicMock()
        mock_get_session.return_value = session
        session.get.return_value = None

        result = initiate_call(str(uuid.uuid4()))
        assert result is None
        session.commit.assert_not_called()

    @patch("app.workers.base.get_sync_session")
    def test_candidate_not_found(self, mock_get_session):
        from app.workers.telephony import initiate_call

        interview = _make_interview()
        session = MagicMock()
        mock_get_session.return_value = session

        def get_side_effect(model_cls, uid):
            name = model_cls.__name__
            if name == "Interview":
                return interview
            return None

        session.get.side_effect = get_side_effect

        result = initiate_call(str(uuid.uuid4()))
        assert result is None
        session.commit.assert_not_called()

    @patch("app.workers.base.get_sync_session")
    def test_position_not_found(self, mock_get_session):
        from app.workers.telephony import initiate_call

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

        result = initiate_call(str(uuid.uuid4()))
        assert result is None
        session.commit.assert_not_called()

    @patch("twilio.rest.Client")
    @patch("app.workers.question_generation.generate_interview_questions")
    @patch("app.core.config.get_settings")
    @patch("app.workers.base.get_sync_session")
    def test_happy_path(self, mock_get_session, mock_settings, mock_gen_questions, mock_twilio_client):
        from app.workers.telephony import initiate_call

        candidate = _make_candidate()
        position = _make_position()
        interview = _make_interview(candidate_id=candidate.id, position_id=position.id)

        session = self._setup_session(interview, candidate, position)
        mock_get_session.return_value = session

        mock_settings.return_value = MagicMock(
            TWILIO_ACCOUNT_SID="AC_test",
            TWILIO_AUTH_TOKEN="auth_test",
            TWILIO_PHONE_NUMBER="+15551234567",
            TWILIO_WEBHOOK_BASE_URL="https://api.aihm.ai",
        )

        mock_gen_questions.return_value = [{"q": "Parlez-moi de Python"}]

        mock_call = MagicMock()
        mock_call.sid = "CA_test_sid_123"
        mock_twilio_client.return_value.calls.create.return_value = mock_call

        initiate_call(str(interview.id))

        assert interview.call_provider_id == "CA_test_sid_123"
        assert interview.status == "in_progress"
        assert interview.started_at is not None
        assert interview.questions_asked == [{"q": "Parlez-moi de Python"}]
        assert candidate.pipeline_status == "call_in_progress"
        session.commit.assert_called_once()

    @patch("twilio.rest.Client")
    @patch("app.workers.question_generation.generate_interview_questions")
    @patch("app.core.config.get_settings")
    @patch("app.workers.base.get_sync_session")
    def test_twilio_error_retries(self, mock_get_session, mock_settings, mock_gen_questions, mock_twilio_client):
        from app.workers.telephony import initiate_call

        candidate = _make_candidate()
        position = _make_position()
        interview = _make_interview(candidate_id=candidate.id, position_id=position.id)

        session = self._setup_session(interview, candidate, position)
        mock_get_session.return_value = session

        mock_settings.return_value = MagicMock(
            TWILIO_ACCOUNT_SID="AC_test",
            TWILIO_AUTH_TOKEN="auth_test",
            TWILIO_PHONE_NUMBER="+15551234567",
            TWILIO_WEBHOOK_BASE_URL="https://api.aihm.ai",
        )

        mock_gen_questions.return_value = [{"q": "test"}]
        mock_twilio_client.return_value.calls.create.side_effect = RuntimeError("Twilio down")

        with pytest.raises(RuntimeError):
            initiate_call(str(interview.id))

        session.rollback.assert_called_once()
        session.close.assert_called_once()

    @patch("twilio.rest.Client")
    @patch("app.workers.question_generation.generate_interview_questions")
    @patch("app.core.config.get_settings")
    @patch("app.workers.base.get_sync_session")
    def test_twiml_url_contains_interview_id(self, mock_get_session, mock_settings, mock_gen_questions, mock_twilio_client):
        from app.workers.telephony import initiate_call

        candidate = _make_candidate()
        position = _make_position()
        interview = _make_interview(candidate_id=candidate.id, position_id=position.id)

        session = self._setup_session(interview, candidate, position)
        mock_get_session.return_value = session

        mock_settings.return_value = MagicMock(
            TWILIO_ACCOUNT_SID="AC_test",
            TWILIO_AUTH_TOKEN="auth_test",
            TWILIO_PHONE_NUMBER="+15551234567",
            TWILIO_WEBHOOK_BASE_URL="https://api.aihm.ai",
        )

        mock_gen_questions.return_value = []
        mock_call = MagicMock()
        mock_call.sid = "CA_xyz"
        mock_twilio_client.return_value.calls.create.return_value = mock_call

        iid = str(interview.id)
        initiate_call(iid)

        call_kwargs = mock_twilio_client.return_value.calls.create.call_args[1]
        assert iid in call_kwargs["url"]
        assert call_kwargs["to"] == candidate.phone
        assert call_kwargs["from_"] == "+15551234567"
        assert call_kwargs["record"] is True


class TestHandleCallStatus:
    @patch("app.workers.telephony.get_sync_session")
    def test_interview_not_found(self, mock_get_session):
        from app.workers.telephony import handle_call_status

        session = MagicMock()
        mock_get_session.return_value = session
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_scalar

        result = handle_call_status("CA_unknown", "completed", 120)
        assert result is None
        session.commit.assert_not_called()

    @patch("app.workers.telephony.get_sync_session")
    def test_completed_status(self, mock_get_session):
        from app.workers.telephony import handle_call_status

        interview = _make_interview()
        candidate = _make_candidate()

        session = MagicMock()
        mock_get_session.return_value = session

        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = interview
        session.execute.return_value = mock_scalar
        session.get.return_value = candidate

        handle_call_status("CA_test", "completed", 300)

        assert interview.status == "completed"
        assert interview.ended_at is not None
        assert interview.duration_seconds == 300
        assert candidate.pipeline_status == "call_done"
        session.commit.assert_called_once()

    @patch("app.workers.telephony.get_sync_session")
    def test_completed_candidate_not_found(self, mock_get_session):
        from app.workers.telephony import handle_call_status

        interview = _make_interview()
        session = MagicMock()
        mock_get_session.return_value = session

        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = interview
        session.execute.return_value = mock_scalar
        session.get.return_value = None

        handle_call_status("CA_test", "completed", 100)

        assert interview.status == "completed"
        session.commit.assert_called_once()

    @patch("app.workers.telephony.get_sync_session")
    def test_busy_status(self, mock_get_session):
        from app.workers.telephony import handle_call_status

        interview = _make_interview()
        session = MagicMock()
        mock_get_session.return_value = session

        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = interview
        session.execute.return_value = mock_scalar

        handle_call_status("CA_test", "busy", 0)

        assert interview.status == "no_answer"
        assert interview.ended_at is not None
        session.commit.assert_called_once()

    @patch("app.workers.telephony.get_sync_session")
    def test_failed_status(self, mock_get_session):
        from app.workers.telephony import handle_call_status

        interview = _make_interview()
        session = MagicMock()
        mock_get_session.return_value = session

        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = interview
        session.execute.return_value = mock_scalar

        handle_call_status("CA_test", "failed", 0)

        assert interview.status == "failed"

    @patch("app.workers.telephony.get_sync_session")
    def test_no_answer_status(self, mock_get_session):
        from app.workers.telephony import handle_call_status

        interview = _make_interview()
        session = MagicMock()
        mock_get_session.return_value = session

        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = interview
        session.execute.return_value = mock_scalar

        handle_call_status("CA_test", "no-answer", 0)

        assert interview.status == "no_answer"

    @patch("app.workers.telephony.get_sync_session")
    def test_canceled_status(self, mock_get_session):
        from app.workers.telephony import handle_call_status

        interview = _make_interview()
        session = MagicMock()
        mock_get_session.return_value = session

        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = interview
        session.execute.return_value = mock_scalar

        handle_call_status("CA_test", "canceled", 0)

        assert interview.status == "no_answer"

    @patch("app.workers.telephony.get_sync_session")
    def test_unknown_status_no_change(self, mock_get_session):
        from app.workers.telephony import handle_call_status

        interview = _make_interview()
        interview.status = "in_progress"
        session = MagicMock()
        mock_get_session.return_value = session

        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = interview
        session.execute.return_value = mock_scalar

        handle_call_status("CA_test", "ringing", 0)

        assert interview.status == "in_progress"
        session.commit.assert_called_once()

    @patch("app.workers.telephony.get_sync_session")
    def test_db_error_rollback(self, mock_get_session):
        from app.workers.telephony import handle_call_status

        session = MagicMock()
        mock_get_session.return_value = session
        session.execute.side_effect = RuntimeError("DB error")

        handle_call_status("CA_test", "completed", 100)

        session.rollback.assert_called_once()
        session.close.assert_called_once()


class TestHandleRecordingReady:
    @patch("app.workers.telephony.get_sync_session")
    def test_interview_not_found(self, mock_get_session):
        from app.workers.telephony import handle_recording_ready

        session = MagicMock()
        mock_get_session.return_value = session
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_scalar

        result = handle_recording_ready("CA_unknown", "https://twilio.com/rec", "RE_123", 60)
        assert result is None

    @patch("app.workers.transcription.transcribe_audio")
    @patch("app.services.storage.ensure_bucket")
    @patch("app.services.storage.s3_client")
    @patch("httpx.get")
    @patch("app.core.config.get_settings")
    @patch("app.workers.telephony.get_sync_session")
    def test_happy_path(self, mock_get_session, mock_settings, mock_httpx_get,
                        mock_s3_client, mock_ensure_bucket, mock_transcribe):
        from app.workers.telephony import handle_recording_ready

        interview = _make_interview()
        session = MagicMock()
        mock_get_session.return_value = session

        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = interview
        session.execute.return_value = mock_scalar

        mock_settings.return_value = MagicMock(
            TWILIO_ACCOUNT_SID="AC_test",
            TWILIO_AUTH_TOKEN="auth_test",
            S3_BUCKET_AUDIO="audio-bucket",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"fake audio data"
        mock_httpx_get.return_value = mock_response

        mock_transcribe.delay = MagicMock()

        handle_recording_ready("CA_test", "https://twilio.com/rec", "RE_abc", 120)

        mock_httpx_get.assert_called_once_with(
            "https://twilio.com/rec.wav", auth=("AC_test", "auth_test")
        )
        mock_ensure_bucket.assert_called_once_with("audio-bucket")
        mock_s3_client.put_object.assert_called_once()
        put_kwargs = mock_s3_client.put_object.call_args[1]
        assert put_kwargs["Bucket"] == "audio-bucket"
        assert put_kwargs["Body"] == b"fake audio data"
        assert put_kwargs["ContentType"] == "audio/wav"
        assert interview.audio_file_path is not None
        session.commit.assert_called_once()
        mock_transcribe.delay.assert_called_once_with(str(interview.id))

    @patch("httpx.get")
    @patch("app.core.config.get_settings")
    @patch("app.workers.telephony.get_sync_session")
    def test_download_failure_no_commit(self, mock_get_session, mock_settings, mock_httpx_get):
        from app.workers.telephony import handle_recording_ready

        interview = _make_interview()
        session = MagicMock()
        mock_get_session.return_value = session

        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = interview
        session.execute.return_value = mock_scalar

        mock_settings.return_value = MagicMock(
            TWILIO_ACCOUNT_SID="AC_test",
            TWILIO_AUTH_TOKEN="auth_test",
            S3_BUCKET_AUDIO="audio-bucket",
        )

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_httpx_get.return_value = mock_response

        handle_recording_ready("CA_test", "https://twilio.com/rec", "RE_abc", 60)

        session.commit.assert_not_called()

    @patch("httpx.get")
    @patch("app.core.config.get_settings")
    @patch("app.workers.telephony.get_sync_session")
    def test_httpx_error_rollback(self, mock_get_session, mock_settings, mock_httpx_get):
        from app.workers.telephony import handle_recording_ready

        interview = _make_interview()
        session = MagicMock()
        mock_get_session.return_value = session

        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = interview
        session.execute.return_value = mock_scalar

        mock_settings.return_value = MagicMock(
            TWILIO_ACCOUNT_SID="AC_test",
            TWILIO_AUTH_TOKEN="auth_test",
            S3_BUCKET_AUDIO="audio-bucket",
        )

        mock_httpx_get.side_effect = ConnectionError("Network error")

        handle_recording_ready("CA_test", "https://twilio.com/rec", "RE_abc", 60)

        session.rollback.assert_called_once()
        session.close.assert_called_once()
