import json
import uuid
from unittest.mock import MagicMock, patch

import pytest


def _make_interview(audio_path="audio-bucket/tenant1/interview1/rec.wav", questions=None):
    i = MagicMock()
    i.id = uuid.uuid4()
    i.candidate_id = uuid.uuid4()
    i.position_id = uuid.uuid4()
    i.tenant_id = uuid.uuid4()
    i.audio_file_path = audio_path
    i.questions_asked = questions
    return i


class TestTranscribeWithWhisper:
    @patch("app.workers.transcription.get_whisper_model")
    def test_happy_path(self, mock_get_model):
        from app.workers.transcription import transcribe_with_whisper

        seg1 = MagicMock()
        seg1.start = 0.0
        seg1.end = 5.0
        seg1.text = "Bonjour je suis candidat"
        seg1.avg_logprob = -0.3

        seg2 = MagicMock()
        seg2.start = 5.0
        seg2.end = 10.0
        seg2.text = "J'ai 5 ans d'experience"
        seg2.avg_logprob = -0.2

        info = MagicMock()
        info.language = "fr"
        info.duration = 10.0

        mock_get_model.return_value.transcribe.return_value = ([seg1, seg2], info)

        result = transcribe_with_whisper(b"fake wav data")

        assert "Bonjour" in result["text"]
        assert "experience" in result["text"]
        assert result["language"] == "fr"
        assert len(result["segments"]) == 2
        assert result["confidence"] == pytest.approx((-0.3 + -0.2) / 2)

    @patch("app.workers.transcription.get_whisper_model")
    def test_empty_segments(self, mock_get_model):
        from app.workers.transcription import transcribe_with_whisper

        info = MagicMock()
        info.language = "fr"
        info.duration = 0.0

        mock_get_model.return_value.transcribe.return_value = ([], info)

        result = transcribe_with_whisper(b"silent audio")

        assert result["text"] == ""
        assert result["confidence"] == 0.0

    @patch("app.workers.transcription.get_whisper_model")
    def test_whisper_error_fallback(self, mock_get_model):
        from app.workers.transcription import transcribe_with_whisper

        mock_get_model.side_effect = RuntimeError("Model load failed")

        result = transcribe_with_whisper(b"audio data")

        assert "simulee" in result["text"]
        assert result["language"] == "fr"
        assert result["confidence"] == 0.0


class TestSegmentTranscription:
    def test_empty_questions(self):
        from app.workers.transcription import segment_transcription

        result = segment_transcription("some text", [])
        assert result == {"full": "some text"}

    def test_empty_text(self):
        from app.workers.transcription import segment_transcription

        result = segment_transcription("", [{"q": "test"}])
        assert result == {"full": ""}

    def test_none_questions(self):
        from app.workers.transcription import segment_transcription

        result = segment_transcription("some text", None)
        assert result == {"full": "some text"}

    @patch("anthropic.Anthropic")
    @patch("app.core.config.get_settings")
    def test_happy_path(self, mock_settings, mock_anthropic_cls):
        from app.workers.transcription import segment_transcription

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")

        segments_result = {
            "segments": [
                {"question_id": 1, "question_text": "Experience?", "answer_text": "5 ans", "duration_estimate_seconds": 30}
            ]
        }
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=json.dumps(segments_result))]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        result = segment_transcription("Candidat repond", [{"q": "Experience?"}])

        assert "segments" in result
        assert result["segments"][0]["answer_text"] == "5 ans"

    @patch("anthropic.Anthropic")
    @patch("app.core.config.get_settings")
    def test_json_in_code_block(self, mock_settings, mock_anthropic_cls):
        from app.workers.transcription import segment_transcription

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")

        segments_result = {"segments": [{"question_id": 1, "answer_text": "ok"}]}
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=f"```json\n{json.dumps(segments_result)}\n```")]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        result = segment_transcription("text", [{"q": "Q1"}])
        assert "segments" in result

    @patch("anthropic.Anthropic")
    @patch("app.core.config.get_settings")
    def test_generic_code_block(self, mock_settings, mock_anthropic_cls):
        from app.workers.transcription import segment_transcription

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")

        segments_result = {"segments": [{"question_id": 1, "answer_text": "ok"}]}
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=f"```\n{json.dumps(segments_result)}\n```")]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        result = segment_transcription("text", [{"q": "Q1"}])
        assert "segments" in result

    @patch("anthropic.Anthropic")
    @patch("app.core.config.get_settings")
    def test_invalid_json_fallback(self, mock_settings, mock_anthropic_cls):
        from app.workers.transcription import segment_transcription

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")

        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="not valid json")]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        result = segment_transcription("full text here", [{"q": "Q1"}])
        assert result == {"full": "full text here"}

    @patch("anthropic.Anthropic")
    @patch("app.core.config.get_settings")
    def test_empty_content_fallback(self, mock_settings, mock_anthropic_cls):
        from app.workers.transcription import segment_transcription

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")

        mock_msg = MagicMock()
        mock_msg.content = []
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        result = segment_transcription("full text here", [{"q": "Q1"}])
        assert result == {"full": "full text here"}


class TestTranscribeAudioTask:
    @patch("app.workers.base.get_sync_session")
    def test_interview_not_found(self, mock_get_session):
        from app.workers.transcription import transcribe_audio

        session = MagicMock()
        mock_get_session.return_value = session
        session.get.return_value = None

        result = transcribe_audio(str(uuid.uuid4()))
        assert result is None
        session.commit.assert_not_called()

    @patch("app.workers.base.get_sync_session")
    def test_no_audio_path(self, mock_get_session):
        from app.workers.transcription import transcribe_audio

        interview = _make_interview(audio_path=None)
        session = MagicMock()
        mock_get_session.return_value = session
        session.get.return_value = interview

        result = transcribe_audio(str(uuid.uuid4()))
        assert result is None
        session.commit.assert_not_called()

    @patch("app.workers.analysis.analyze_interview")
    @patch("app.workers.transcription.segment_transcription")
    @patch("app.workers.transcription.transcribe_with_whisper")
    @patch("app.services.storage.download_file")
    @patch("app.workers.base.get_sync_session")
    def test_happy_path(self, mock_get_session, mock_download, mock_whisper,
                        mock_segment, mock_analyze):
        from app.workers.transcription import transcribe_audio

        interview = _make_interview(
            audio_path="audio-bucket/tenant1/interview1/rec.wav",
            questions=[{"q": "Experience?"}],
        )

        session = MagicMock()
        mock_get_session.return_value = session
        session.get.return_value = interview

        mock_download.return_value = b"audio bytes"
        mock_whisper.return_value = {
            "text": "J'ai 5 ans d'experience Python",
            "language": "fr",
            "confidence": -0.25,
        }
        mock_segment.return_value = {"segments": [{"q": 1, "answer": "5 ans"}]}
        mock_analyze.delay = MagicMock()

        transcribe_audio(str(interview.id))

        mock_download.assert_called_once_with("audio-bucket", "tenant1/interview1/rec.wav")
        mock_whisper.assert_called_once_with(b"audio bytes")
        mock_segment.assert_called_once()
        session.add.assert_called_once()
        session.commit.assert_called_once()
        mock_analyze.delay.assert_called_once_with(str(interview.id))

        transcription_obj = session.add.call_args[0][0]
        assert transcription_obj.full_text == "J'ai 5 ans d'experience Python"
        assert transcription_obj.language_detected == "fr"
        assert transcription_obj.confidence_score == -0.25

    @patch("app.workers.transcription.transcribe_with_whisper")
    @patch("app.services.storage.download_file")
    @patch("app.workers.base.get_sync_session")
    def test_whisper_error_retries(self, mock_get_session, mock_download, mock_whisper):
        from app.workers.transcription import transcribe_audio

        interview = _make_interview()
        session = MagicMock()
        mock_get_session.return_value = session
        session.get.return_value = interview

        mock_download.return_value = b"audio"
        mock_whisper.side_effect = RuntimeError("Whisper crashed")

        with pytest.raises(RuntimeError):
            transcribe_audio(str(interview.id))

        session.rollback.assert_called_once()
        session.close.assert_called_once()

    @patch("app.workers.analysis.analyze_interview")
    @patch("app.workers.transcription.segment_transcription")
    @patch("app.workers.transcription.transcribe_with_whisper")
    @patch("app.services.storage.download_file")
    @patch("app.workers.base.get_sync_session")
    def test_no_questions_segments_full(self, mock_get_session, mock_download, mock_whisper,
                                        mock_segment, mock_analyze):
        from app.workers.transcription import transcribe_audio

        interview = _make_interview(questions=None)

        session = MagicMock()
        mock_get_session.return_value = session
        session.get.return_value = interview

        mock_download.return_value = b"audio"
        mock_whisper.return_value = {"text": "hello", "language": "en", "confidence": -0.1}
        mock_segment.return_value = {"full": "hello"}
        mock_analyze.delay = MagicMock()

        transcribe_audio(str(interview.id))

        mock_segment.assert_called_once_with("hello", [])
        session.add.assert_called_once()


class TestGetWhisperModel:
    @patch("app.core.config.get_settings")
    def test_loads_model_once(self, mock_settings):
        import app.workers.transcription as mod

        mock_settings.return_value = MagicMock(
            WHISPER_MODEL="large-v3",
            WHISPER_DEVICE="cpu",
            WHISPER_COMPUTE_TYPE="int8",
        )

        mock_whisper_cls = MagicMock()
        mock_model = MagicMock()
        mock_whisper_cls.return_value = mock_model

        old_val = mod._whisper_model
        mod._whisper_model = None
        try:
            with patch.dict("sys.modules", {"faster_whisper": MagicMock(WhisperModel=mock_whisper_cls)}):
                result = mod.get_whisper_model()

            assert result == mock_model
            mock_whisper_cls.assert_called_once_with("large-v3", device="cpu", compute_type="int8")
        finally:
            mod._whisper_model = old_val
