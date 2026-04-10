from datetime import datetime, timezone
from uuid import UUID

import structlog
from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import Response
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import async_session
from app.models.interview import Interview
from app.services.call_safety import classify_answer, decide_action
from app.services.answer_evaluator import evaluate_answer, AnswerQuality

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


@router.post("/voice")
async def conversation_voice_handler(
    request: Request,
    interview_id: str = Query(""),
) -> Response:
    """
    Entry point for incoming call. Twilio calls this when candidate picks up.
    Returns TwiML with intro + Q0 using text-to-speech.
    """
    logger.info("conversation_voice_handler_start", interview_id=interview_id)

    questions = []
    candidate_name = "candidat"

    if interview_id:
        try:
            async with async_session() as db:
                result = await db.execute(
                    select(Interview).where(Interview.id == UUID(interview_id))
                )
                interview = result.scalar_one_or_none()
                if interview:
                    questions = interview.questions_asked or []

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
            logger.error("conversation_voice_handler_db_error", interview_id=interview_id, error=str(e))

    if not questions:
        logger.warning("no_questions_found", interview_id=interview_id)
        return _build_twiml_response(
            "<Response>"
            '<Say language="fr-FR" voice="Polly.Lea">'
            "Il y a eu un problème technique. Veuillez réessayer plus tard."
            "</Say>"
            "</Response>"
        )

    settings = get_settings()
    timeout = settings.CONVERSATION_GATHER_TIMEOUT

    # Build intro text with candidate personalization
    intro_text = (
        f"Bonjour {candidate_name}. Je suis l'assistant de recrutement. "
        "Cet appel est enregistré avec votre consentement. "
        "Je vais vous poser quelques questions. Prenez le temps de répondre complètement. "
        "Commençons."
    )

    q0_text = questions[0].get("text", "") if questions else ""
    q0_full = f"Question 1. {q0_text}"

    twiml = (
        "<Response>"
        f'  <Say language="fr-FR" voice="Polly.Lea">{_escape_xml(intro_text)}</Say>'
        f'  <Gather input="speech" timeout="{timeout + 3}" speechTimeout="auto" '
        f'language="fr-FR" '
        f'action="/api/v1/webhooks/conv/answer?interview_id={interview_id}&amp;question_idx=0&amp;retry_count=0" '
        f'method="POST">'
        f'    <Say language="fr-FR" voice="Polly.Lea">{_escape_xml(q0_full)}</Say>'
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
    questions = []

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

    # Evaluate answer quality (only if safety check passed)
    quality_result = None
    if safety_result.label.value == "normal" and SpeechResult.strip():
        quality_result = await evaluate_answer(
            speech_result=SpeechResult,
            question_text=question_text,
            question_id=question_idx,
        )

    # Decide action based on safety and quality
    action = decide_action(safety_result, retry_count, settings.CONVERSATION_MAX_RETRIES)

    # If off-scope (user asked a question), treat it like poor quality (ask confirmation)
    if safety_result.label.value == "off_scope":
        action = "confirm_reask"  # Override redirect with confirmation prompt
    # Override action if quality is poor (ask for confirmation and repose)
    elif quality_result and quality_result.label == AnswerQuality.POOR:
        action = "confirm_reask"  # Custom action for poor quality
    elif quality_result and quality_result.label == AnswerQuality.MEDIUM:
        action = "clarify_reask"  # Custom action for medium quality

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
        "answer_quality": quality_result.label.value if quality_result else "not_evaluated",
        "quality_relevance_score": quality_result.relevance_score if quality_result else 0,
        "quality_depth_score": quality_result.depth_score if quality_result else 0,
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

    # Handle poor quality: ask for confirmation
    if action == "confirm_reask":
        confirm_text = (
            f"Êtes-vous sûr de vouloir soumettre cette réponse? "
            f"Elle ne semble pas directement liée à ma question. "
            f"Revenons à : {question_text}"
        )
        twiml = (
            "<Response>"
            f'  <Gather input="speech" timeout="{timeout + 3}" speechTimeout="auto" '
            f'language="fr-FR" '
            f'action="/api/v1/webhooks/conv/answer?interview_id={interview_id}&amp;question_idx={question_idx}&amp;retry_count={retry_count + 1}" '
            f'method="POST">'
            f'    <Say language="fr-FR" voice="Polly.Lea">{_escape_xml(confirm_text)}</Say>'
            f"  </Gather>"
            f'  <Redirect>/api/v1/webhooks/conv/answer?interview_id={interview_id}&amp;question_idx={question_idx}&amp;retry_count={retry_count + 1}</Redirect>'
            "</Response>"
        )
        logger.info(
            "confirm_reask_twiml_returned",
            interview_id=interview_id,
            question_idx=question_idx,
            reason="poor_quality",
        )
        return _build_twiml_response(twiml)

    # Handle medium quality: ask for clarification
    if action == "clarify_reask":
        clarify_text = (
            f"Merci pour votre réponse. Pouvez-vous préciser davantage? "
            f"{question_text}"
        )
        twiml = (
            "<Response>"
            f'  <Gather input="speech" timeout="{timeout + 3}" speechTimeout="auto" '
            f'language="fr-FR" '
            f'action="/api/v1/webhooks/conv/answer?interview_id={interview_id}&amp;question_idx={question_idx}&amp;retry_count={retry_count + 1}" '
            f'method="POST">'
            f'    <Say language="fr-FR" voice="Polly.Lea">{_escape_xml(clarify_text)}</Say>'
            f"  </Gather>"
            f'  <Redirect>/api/v1/webhooks/conv/answer?interview_id={interview_id}&amp;question_idx={question_idx}&amp;retry_count={retry_count + 1}</Redirect>'
            "</Response>"
        )
        logger.info(
            "clarify_reask_twiml_returned",
            interview_id=interview_id,
            question_idx=question_idx,
            reason="medium_quality",
        )
        return _build_twiml_response(twiml)

    if action == "retry" and retry_count < settings.CONVERSATION_MAX_RETRIES:
        # Retry same question with off-scope message
        # Check if this is due to off-scope (user asking questions instead of answering)
        is_off_scope = safety_result.label.value == "off_scope"

        if is_off_scope:
            retry_text = (
                "Je suis désolé, je ne peux pas répondre à cette question. "
                f"Revenons à l'entretien. {question_text}"
            )
        else:
            retry_text = (
                f"Je n'ai pas bien entendu votre réponse. "
                f"Pourriez-vous répéter ? {question_text}"
            )

        twiml = (
            "<Response>"
            f'  <Gather input="speech" timeout="{timeout + 3}" speechTimeout="auto" '
            f'language="fr-FR" '
            f'action="/api/v1/webhooks/conv/answer?interview_id={interview_id}&amp;question_idx={question_idx}&amp;retry_count={retry_count + 1}" '
            f'method="POST">'
            f'    <Say language="fr-FR" voice="Polly.Lea">{_escape_xml(retry_text)}</Say>'
            f"  </Gather>"
            f'  <Redirect>/api/v1/webhooks/conv/answer?interview_id={interview_id}&amp;question_idx={question_idx}&amp;retry_count={retry_count + 1}</Redirect>'
            "</Response>"
        )
        logger.info(
            "retry_twiml_returned",
            interview_id=interview_id,
            question_idx=question_idx,
            retry_count=retry_count + 1,
            reason="off_scope" if is_off_scope else "unclear",
        )
        return _build_twiml_response(twiml)

    # Move to next question
    next_idx = question_idx + 1

    if next_idx >= len(questions):
        # Outro
        outro_text = (
            "Merci beaucoup pour vos réponses. L'entretien est maintenant terminé. "
            "Vous recevrez un retour dans les prochains jours. Bonne journée."
        )
        twiml = (
            "<Response>"
            f'  <Say language="fr-FR" voice="Polly.Lea">{_escape_xml(outro_text)}</Say>'
            f"  <Hangup/>"
            "</Response>"
        )
        logger.info(
            "outro_twiml_returned",
            interview_id=interview_id,
            total_questions=len(questions),
        )
        return _build_twiml_response(twiml)

    if action == "redirect":
        # Off-scope/injection redirect, then next question
        redirect_text = (
            "Je suis désolé, je ne peux pas répondre à cette question. "
            "Revenons à l'entretien."
        )
        next_text = questions[next_idx].get("text", "") if next_idx < len(questions) else ""
        next_full = f"Question {next_idx + 1}. {next_text}"

        twiml = (
            "<Response>"
            f'  <Say language="fr-FR" voice="Polly.Lea">{_escape_xml(redirect_text)}</Say>'
            f'  <Gather input="speech" timeout="{timeout + 3}" speechTimeout="auto" '
            f'language="fr-FR" '
            f'action="/api/v1/webhooks/conv/answer?interview_id={interview_id}&amp;question_idx={next_idx}&amp;retry_count=0" '
            f'method="POST">'
            f'    <Say language="fr-FR" voice="Polly.Lea">{_escape_xml(next_full)}</Say>'
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
    next_text = questions[next_idx].get("text", "") if next_idx < len(questions) else ""
    next_full = f"Question {next_idx + 1}. {next_text}"

    twiml = (
        "<Response>"
        f'  <Gather input="speech" timeout="{timeout + 3}" speechTimeout="auto" '
        f'language="fr-FR" '
        f'action="/api/v1/webhooks/conv/answer?interview_id={interview_id}&amp;question_idx={next_idx}&amp;retry_count=0" '
        f'method="POST">'
        f'    <Say language="fr-FR" voice="Polly.Lea">{_escape_xml(next_full)}</Say>'
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
