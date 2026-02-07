import json
from datetime import datetime, timezone

import structlog
from celery import shared_task

logger = structlog.get_logger()


@shared_task(name="telephony.initiate_call", bind=True, max_retries=2)
def initiate_call(self, interview_id: str):
    logger.info("call_initiate_start", interview_id=interview_id)

    from app.workers.cv_processing import get_sync_session

    session = get_sync_session()
    try:
        from uuid import UUID

        from app.core.config import get_settings
        from app.models.candidate import Candidate
        from app.models.interview import Interview
        from app.models.position import Position

        settings = get_settings()
        interview = session.get(Interview, UUID(interview_id))
        if not interview:
            return

        candidate = session.get(Candidate, interview.candidate_id)
        position = session.get(Position, interview.position_id)

        # Generate questions for this interview
        from app.workers.question_generation import generate_interview_questions

        questions = generate_interview_questions(candidate, position)
        interview.questions_asked = questions

        # Initiate Twilio call
        from twilio.rest import Client

        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

        twiml_url = (
            f"{settings.TWILIO_WEBHOOK_BASE_URL}/api/v1/webhooks/twilio/voice"
            f"?interview_id={interview_id}"
        )

        call = client.calls.create(
            to=candidate.phone,
            from_=settings.TWILIO_PHONE_NUMBER,
            url=twiml_url,
            status_callback=f"{settings.TWILIO_WEBHOOK_BASE_URL}/api/v1/webhooks/twilio/status",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
            record=True,
            recording_status_callback=(
                f"{settings.TWILIO_WEBHOOK_BASE_URL}/api/v1/webhooks/twilio/recording"
            ),
            timeout=30,
        )

        interview.call_provider_id = call.sid
        interview.status = "in_progress"
        interview.started_at = datetime.now(timezone.utc)

        candidate.pipeline_status = "call_in_progress"

        session.commit()
        logger.info("call_initiated", interview_id=interview_id, call_sid=call.sid)

    except Exception as e:
        session.rollback()
        logger.error("call_initiate_error", interview_id=interview_id, error=str(e))
        raise self.retry(exc=e, countdown=60)
    finally:
        session.close()


@shared_task(name="telephony.handle_call_status")
def handle_call_status(call_sid: str, call_status: str, duration: int):
    logger.info("call_status_update", call_sid=call_sid, status=call_status, duration=duration)

    from app.workers.cv_processing import get_sync_session

    session = get_sync_session()
    try:
        from sqlalchemy import select

        from app.models.candidate import Candidate
        from app.models.interview import Interview

        result = session.execute(
            select(Interview).where(Interview.call_provider_id == call_sid)
        )
        interview = result.scalar_one_or_none()
        if not interview:
            logger.warning("call_status_no_interview", call_sid=call_sid)
            return

        if call_status == "completed":
            interview.status = "completed"
            interview.ended_at = datetime.now(timezone.utc)
            interview.duration_seconds = duration

            candidate = session.get(Candidate, interview.candidate_id)
            if candidate:
                candidate.pipeline_status = "call_done"

        elif call_status in ("busy", "no-answer", "failed", "canceled"):
            interview.status = "failed" if call_status == "failed" else "no_answer"
            interview.ended_at = datetime.now(timezone.utc)

        session.commit()

    except Exception as e:
        session.rollback()
        logger.error("call_status_error", call_sid=call_sid, error=str(e))
    finally:
        session.close()


@shared_task(name="telephony.handle_recording_ready")
def handle_recording_ready(call_sid: str, recording_url: str, recording_sid: str, duration: int):
    logger.info("recording_ready", call_sid=call_sid, recording_sid=recording_sid)

    from app.workers.cv_processing import get_sync_session

    session = get_sync_session()
    try:
        from sqlalchemy import select

        from app.models.interview import Interview

        result = session.execute(
            select(Interview).where(Interview.call_provider_id == call_sid)
        )
        interview = result.scalar_one_or_none()
        if not interview:
            return

        # Download recording from Twilio and store in MinIO
        import httpx

        from app.core.config import get_settings
        from app.services.storage import ensure_bucket, s3_client

        settings = get_settings()
        auth = (settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

        response = httpx.get(f"{recording_url}.wav", auth=auth)
        if response.status_code == 200:
            bucket = settings.S3_BUCKET_AUDIO
            ensure_bucket(bucket)
            key = f"{interview.tenant_id}/{interview.id}/{recording_sid}.wav"
            s3_client.put_object(
                Bucket=bucket, Key=key, Body=response.content, ContentType="audio/wav"
            )
            interview.audio_file_path = f"{bucket}/{key}"
            session.commit()

            # Trigger transcription
            from app.workers.transcription import transcribe_audio

            transcribe_audio.delay(str(interview.id))

    except Exception as e:
        session.rollback()
        logger.error("recording_error", call_sid=call_sid, error=str(e))
    finally:
        session.close()
