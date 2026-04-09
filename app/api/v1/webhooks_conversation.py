from datetime import datetime, timezone
from uuid import UUID

import structlog
from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import Response
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import async_session
from app.models.interview import Interview
from app.services.call_safety import SafetyLabel, classify_answer, decide_action
from app.services.tts_service import generate_presigned_url_from_key

logger = structlog.get_logger()

router = APIRouter(prefix="/webhooks/conv", tags=["webhooks-conversation"])


def _escape_xml(text: str) -> str:
    """Escape text for safe XML inclusion in TwiML."""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _build_twiml_response(content: str) -> Response:
    """Build TwiML response with proper XML headers."""
    xml = f'<?xml version="1.0" encoding="UTF-8"?>\n{content}'
    return Response(content=xml, media_type="application/xml")


def _extract_minio_key_from_url(url: str) -> str:
    """
    Extract MinIO object key from a presigned URL.
    URL format: http://minio:9000/tts-audio/interview-id/intro.mp3?X-Amz-...
    Returns: interview-id/intro.mp3 (the key within the tts-audio bucket)
    """
    if not url:
        return ""
    try:
        # Find the path part (after the domain, before query string)
        if "?" in url:
            path = url.split("?")[0]
        else:
            path = url

        # Extract everything after /tts-audio/
        # URL: http://minio:9000/tts-audio/interview-id/intro.mp3
        # We want: interview-id/intro.mp3
        if "/tts-audio/" in path:
            return path.split("/tts-audio/", 1)[1]
    except Exception as e:
        logger.error("extract_minio_key_error", url=url[:100], error=str(e))
    return ""


def _refresh_tts_url(url: str) -> str:
    """
    Refresh a presigned URL by extracting the MinIO key and generating a fresh URL.
    This ensures URLs never expire.
    """
    if not url:
        return url
    key = _extract_minio_key_from_url(url)
    if not key:
        return url
    try:
        return generate_presigned_url_from_key(key)
    except Exception as e:
        logger.error("refresh_tts_url_error", key=key, error=str(e))
        return url


def _normalize_tts_url(url: str) -> str:
    """Replace internal Docker endpoint with external endpoint for Twilio access."""
    if not url:
        return url
    settings = get_settings()
    if "http://minio:9000" in url:
        external_endpoint = getattr(settings, "S3_EXTERNAL_ENDPOINT", "http://localhost:9000")
        return url.replace("http://minio:9000", external_endpoint)
    return url


def _refresh_tts_urls_dict(urls: dict) -> dict:
    """
    Refresh all TTS presigned URLs in the dict by regenerating them from MinIO keys.
    This ensures URLs are always fresh and never expire.
    """
    if not urls:
        return urls
    refreshed = {key: _refresh_tts_url(url) for key, url in urls.items()}
    logger.info("urls_refreshed", num_urls=len(refreshed), sample_url=list(refreshed.values())[0][:80] if refreshed else "none")
    return refreshed


@router.post("/voice")
async def conversation_voice_handler(
    request: Request,
    interview_id: str = Query(""),
) -> Response:
    """
    Entry point for incoming call. Twilio calls this when candidate picks up.
    Returns TwiML with intro + Q0 in a single <Gather> for barge-in.
    """
    logger.info("conversation_voice_handler_start", interview_id=interview_id)

    questions = []
    tts_urls = {}
    candidate_name = "candidat"

    if interview_id:
        try:
            async with async_session() as db:
                logger.info("db_session_created", interview_id=interview_id)
                result = await db.execute(
                    select(Interview).where(Interview.id == UUID(interview_id))
                )
                interview = result.scalar_one_or_none()
                logger.info("interview_fetched", interview_id=interview_id, found=interview is not None)
                if interview:
                    raw_tts_urls = interview.tts_audio_urls or {}
                    logger.info("raw_tts_urls_from_db", num_urls=len(raw_tts_urls), sample_url=str(list(raw_tts_urls.values())[0])[:80] if raw_tts_urls else "none")
                    questions = interview.questions_asked or []
                    tts_urls = _refresh_tts_urls_dict(raw_tts_urls)
                    logger.info("urls_normalized_in_handler", num_urls=len(tts_urls), sample_url=str(list(tts_urls.values())[0])[:80] if tts_urls else "none")

                    # Fetch candidate name for personalization
                    if interview.candidate_id:
                        from app.models.candidate import Candidate

                        cand_result = await db.execute(
                            select(Candidate).where(Candidate.id == interview.candidate_id)
                        )
                        candidate = cand_result.scalar_one_or_none()
                        if candidate:
                            candidate_name = candidate.name or "candidat"
        except Exception as e:
            logger.error("conversation_voice_handler_db_error", interview_id=interview_id, error=str(e), traceback=True)

    # Build TwiML with intro + Q0 in one Gather
    settings = get_settings()

    if not tts_urls or "intro" not in tts_urls or not questions:
        # Fallback if TTS pre-generation failed
        logger.warning(
            "missing_tts_urls_or_questions",
            interview_id=interview_id,
            has_urls=bool(tts_urls),
            num_questions=len(questions),
        )
        return _build_twiml_response(
            "<Response>"
            '<Say language="fr-FR" voice="Polly.Lea">'
            "Il y a eu un problème technique. Veuillez réessayer plus tard."
            "</Say>"
            "</Response>"
        )

    intro_url = _escape_xml(_normalize_tts_url(tts_urls.get("intro", "")))
    q0_url = _escape_xml(_normalize_tts_url(tts_urls.get("q0", "")))
    timeout = settings.CONVERSATION_GATHER_TIMEOUT

    twiml = (
        "<Response>"
        f'  <Gather input="speech" timeout="{timeout + 3}" speechTimeout="auto" '
        f'language="fr-FR" '
        f'action="/api/v1/webhooks/conv/answer?interview_id={interview_id}&amp;question_idx=0&amp;retry_count=0" '
        f'method="POST">'
        f'    <Play>{intro_url}</Play>'
        f'    <Play>{q0_url}</Play>'
        f"  </Gather>"
        f'  <Redirect>/api/v1/webhooks/conv/answer?interview_id={interview_id}&amp;question_idx=0&amp;retry_count=0</Redirect>'
        "</Response>"
    )

    logger.info(
        "conversation_voice_handler_success",
        interview_id=interview_id,
        candidate_name=candidate_name,
        num_questions=len(questions),
    )
    return _build_twiml_response(twiml)


@router.post("/answer")
async def conversation_answer_handler(
    request: Request,
    interview_id: str = Query(""),
    question_idx: int = Query(0),
    retry_count: int = Query(0),
    SpeechResult: str = Form(""),
    Confidence: str = Form("0"),
    CallStatus: str = Form(""),
) -> Response:
    """
    Handle each candidate answer. Called by Twilio after Gather completes.
    Steps:
      1. Parse response (SpeechResult + Confidence from Twilio)
      2. Run safety classification
      3. Persist per-question metric
      4. Decide: continue | retry | redirect | skip | outro
      5. Return next TwiML
    """
    logger.info(
        "conversation_answer_handler_start",
        interview_id=interview_id,
        question_idx=question_idx,
        retry_count=retry_count,
        twilio_confidence=Confidence,
    )

    confidence_float = float(Confidence or 0)
    settings = get_settings()
    interview = None
    questions = []
    tts_urls = {}

    # Load interview from DB
    try:
        async with async_session() as db:
            result = await db.execute(
                select(Interview).where(Interview.id == UUID(interview_id))
            )
            interview = result.scalar_one_or_none()
            if not interview:
                logger.error("interview_not_found", interview_id=interview_id)
                return _build_twiml_response(
                    "<Response>"
                    '<Say language="fr-FR" voice="Polly.Lea">'
                    "Entretien non trouvé."
                    "</Say>"
                    "</Response>"
                )

            questions = interview.questions_asked or []
            tts_urls = interview.tts_audio_urls or {}
    except Exception as e:
        logger.error(
            "conversation_answer_handler_db_load_error",
            interview_id=interview_id,
            error=str(e),
        )
        return _build_twiml_response(
            "<Response>"
            '<Say language="fr-FR" voice="Polly.Lea">'
            "Erreur technique."
            "</Say>"
            "</Response>"
        )

    # Safety classification
    question_text = questions[question_idx].get("text", "") if question_idx < len(questions) else ""
    safety_result = await classify_answer(
        speech_result=SpeechResult,
        confidence=confidence_float,
        question_id=question_idx,
        question_text=question_text,
    )

    # Decide action
    action = decide_action(safety_result, retry_count, settings.CONVERSATION_MAX_RETRIES)

    # Persist metric
    metric = {
        "question_idx": question_idx,
        "question_id": questions[question_idx].get("id", question_idx)
        if question_idx < len(questions)
        else question_idx,
        "partial_transcript": SpeechResult[:500] if SpeechResult else "",
        "twilio_confidence": confidence_float,
        "retry_count": retry_count,
        "safety_classification": safety_result.label.value,
        "safety_confidence": safety_result.confidence,
        "action_taken": action,
        "answered_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    try:
        async with async_session() as db:
            result = await db.execute(
                select(Interview).where(Interview.id == UUID(interview_id))
            )
            interview = result.scalar_one_or_none()
            if interview:
                existing = interview.conversation_metrics or []
                # Replace if already exists for this question_idx (retry case)
                existing = [m for m in existing if m.get("question_idx") != question_idx]
                existing.append(metric)
                interview.conversation_metrics = existing
                await db.commit()
                logger.info("metric_persisted", interview_id=interview_id, question_idx=question_idx)
    except Exception as e:
        logger.error(
            "metric_persistence_error",
            interview_id=interview_id,
            question_idx=question_idx,
            error=str(e),
        )

    # Build next TwiML based on action
    timeout = settings.CONVERSATION_GATHER_TIMEOUT

    if action == "retry" and retry_count < settings.CONVERSATION_MAX_RETRIES:
        # Retry same question
        retry_key = f"retry_q{question_idx}"
        if retry_key in tts_urls:
            retry_url = _escape_xml(tts_urls[retry_key])
            twiml = (
                "<Response>"
                f'  <Gather input="speech" timeout="{timeout + 3}" speechTimeout="auto" '
                f'language="fr-FR" '
                f'action="/api/v1/webhooks/conv/answer?interview_id={interview_id}&amp;question_idx={question_idx}&amp;retry_count={retry_count + 1}" '
                f'method="POST">'
                f'    <Play>{retry_url}</Play>'
                f"  </Gather>"
                f'  <Redirect>/api/v1/webhooks/conv/answer?interview_id={interview_id}&amp;question_idx={question_idx}&amp;retry_count={retry_count + 1}</Redirect>'
                "</Response>"
            )
            logger.info(
                "retry_twiml_returned",
                interview_id=interview_id,
                question_idx=question_idx,
                retry_count=retry_count + 1,
            )
            return _build_twiml_response(twiml)

    # Move to next question
    next_idx = question_idx + 1

    if next_idx >= len(questions):
        # Outro
        outro_url = _escape_xml(tts_urls.get("outro", ""))
        twiml = "<Response>" f'  <Play>{outro_url}</Play>' f"  <Hangup/>" "</Response>"
        logger.info(
            "outro_twiml_returned",
            interview_id=interview_id,
            total_questions=len(questions),
        )
        return _build_twiml_response(twiml)

    if action == "redirect":
        # Off-scope/injection redirect, then next question
        redirect_url = _escape_xml(tts_urls.get("off_scope_redirect", ""))
        next_url = _escape_xml(tts_urls.get(f"q{next_idx}", ""))
        twiml = (
            "<Response>"
            f'  <Play>{redirect_url}</Play>'
            f'  <Gather input="speech" timeout="{timeout + 3}" speechTimeout="auto" '
            f'language="fr-FR" '
            f'action="/api/v1/webhooks/conv/answer?interview_id={interview_id}&amp;question_idx={next_idx}&amp;retry_count=0" '
            f'method="POST">'
            f'    <Play>{next_url}</Play>'
            f"  </Gather>"
            f'  <Redirect>/api/v1/webhooks/conv/answer?interview_id={interview_id}&amp;question_idx={next_idx}&amp;retry_count=0</Redirect>'
            "</Response>"
        )
        logger.info(
            "redirect_twiml_returned",
            interview_id=interview_id,
            from_question_idx=question_idx,
            to_question_idx=next_idx,
            reason=safety_result.label.value,
        )
        return _build_twiml_response(twiml)

    # Normal continue to next question
    next_url = _escape_xml(tts_urls.get(f"q{next_idx}", ""))
    twiml = (
        "<Response>"
        f'  <Gather input="speech" timeout="{timeout + 3}" speechTimeout="auto" '
        f'language="fr-FR" '
        f'action="/api/v1/webhooks/conv/answer?interview_id={interview_id}&amp;question_idx={next_idx}&amp;retry_count=0" '
        f'method="POST">'
        f'    <Play>{next_url}</Play>'
        f"  </Gather>"
        f'  <Redirect>/api/v1/webhooks/conv/answer?interview_id={interview_id}&amp;question_idx={next_idx}&amp;retry_count=0</Redirect>'
        "</Response>"
    )
    logger.info(
        "continue_twiml_returned",
        interview_id=interview_id,
        from_question_idx=question_idx,
        to_question_idx=next_idx,
    )
    return _build_twiml_response(twiml)
