import json

import structlog
from celery import shared_task

logger = structlog.get_logger()

_whisper_model = None


def get_whisper_model():
    """Load faster-whisper model (cached after first call)."""
    global _whisper_model
    if _whisper_model is None:
        from app.core.config import get_settings

        settings = get_settings()
        from faster_whisper import WhisperModel

        _whisper_model = WhisperModel(
            settings.WHISPER_MODEL,
            device=settings.WHISPER_DEVICE,
            compute_type=settings.WHISPER_COMPUTE_TYPE,
        )
        logger.info(
            "whisper_model_loaded",
            model=settings.WHISPER_MODEL,
            device=settings.WHISPER_DEVICE,
        )
    return _whisper_model


@shared_task(name="transcription.transcribe", bind=True, max_retries=3)
def transcribe_audio(self, interview_id: str):
    logger.info("transcription_start", interview_id=interview_id)

    from app.workers.cv_processing import get_sync_session

    session = get_sync_session()
    try:
        from uuid import UUID

        from app.models.interview import Interview
        from app.models.transcription import Transcription

        interview = session.get(Interview, UUID(interview_id))
        if not interview or not interview.audio_file_path:
            logger.warning("transcription_skip", interview_id=interview_id)
            return

        # Download audio from MinIO
        from app.services.storage import download_file

        parts = interview.audio_file_path.split("/", 1)
        audio_data = download_file(parts[0], parts[1])

        # Transcribe with faster-whisper (fallback to simulated)
        result = transcribe_with_whisper(audio_data)

        # Segment by questions
        segments = segment_transcription(result["text"], interview.questions_asked or [])

        transcription = Transcription(
            interview_id=interview.id,
            full_text=result["text"],
            segments=segments,
            language_detected=result.get("language", "fr"),
            confidence_score=result.get("confidence", 0.0),
        )
        session.add(transcription)
        session.commit()

        logger.info("transcription_done", interview_id=interview_id)

        # Trigger analysis
        from app.workers.analysis import analyze_interview

        analyze_interview.delay(interview_id)

    except Exception as e:
        session.rollback()
        logger.error("transcription_error", interview_id=interview_id, error=str(e))
        raise self.retry(exc=e, countdown=30)
    finally:
        session.close()


def transcribe_with_whisper(audio_data: bytes) -> dict:
    """Transcribe audio using faster-whisper. Falls back if unavailable."""
    import os
    import tempfile

    try:
        model = get_whisper_model()

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_data)
            temp_path = f.name

        segments, info = model.transcribe(temp_path, beam_size=5, language="fr")

        all_segments = []
        full_text_parts = []
        for segment in segments:
            all_segments.append(
                {
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                    "avg_logprob": segment.avg_logprob,
                }
            )
            full_text_parts.append(segment.text)

        os.unlink(temp_path)

        avg_confidence = sum(s["avg_logprob"] for s in all_segments) / max(len(all_segments), 1)

        logger.info(
            "whisper_transcription_complete",
            language=info.language,
            duration=info.duration,
            num_segments=len(all_segments),
        )

        return {
            "text": " ".join(full_text_parts).strip(),
            "language": info.language,
            "segments": all_segments,
            "confidence": avg_confidence,
        }
    except Exception as e:
        logger.warning("whisper_fallback", error=str(e))
        return {
            "text": "[Transcription simulee - faster-whisper non disponible]",
            "language": "fr",
            "confidence": 0.0,
        }


def segment_transcription(full_text: str, questions: list[dict]) -> dict:
    """Segment the transcription by questions asked."""
    if not questions or not full_text:
        return {"full": full_text}

    from anthropic import Anthropic

    from app.core.config import get_settings

    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=1500,
        messages=[
            {
                "role": "user",
                "content": f"""Segmente cette transcription par question posee. Reponds en JSON.

QUESTIONS POSEES:
{json.dumps(questions, ensure_ascii=False)}

TRANSCRIPTION COMPLETE:
{full_text[:3000]}

Format JSON:
{{
    "segments": [
        {{
            "question_id": 1,
            "question_text": "...",
            "answer_text": "la reponse du candidat",
            "duration_estimate_seconds": 30
        }}
    ]
}}""",
            }
        ],
    )

    try:
        text_content = response.content[0].text
        if "```json" in text_content:
            text_content = text_content.split("```json")[1].split("```")[0]
        elif "```" in text_content:
            text_content = text_content.split("```")[1].split("```")[0]
        return json.loads(text_content.strip())
    except (json.JSONDecodeError, IndexError):
        return {"full": full_text}
