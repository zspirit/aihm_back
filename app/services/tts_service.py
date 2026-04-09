import asyncio
import io

import edge_tts
import structlog

from app.core.config import get_settings
from app.services.storage import ensure_bucket, s3_client

logger = structlog.get_logger()

TTS_BUCKET = "tts-audio"


async def generate_tts_mp3(
    text: str,
    voice: str = "fr-FR-HenriNeural",
    rate: str = "-5%",
) -> bytes:
    """
    Generate MP3 bytes from text using edge-tts (Microsoft Neural TTS).
    Returns raw MP3 bytes in memory.

    Args:
        text: Text to synthesize
        voice: Edge-TTS voice code (e.g., "fr-FR-HenriNeural", "fr-FR-DeniseNeural")
        rate: Speech rate modifier (e.g., "-5%" for slower, "+10%" for faster)

    Returns:
        MP3 bytes ready to be saved or uploaded
    """
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    mp3_buffer = io.BytesIO()

    try:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_buffer.write(chunk["data"])
    except Exception as e:
        logger.error("edge_tts_generation_error", text_length=len(text), voice=voice, error=str(e))
        raise

    mp3_buffer.seek(0)
    return mp3_buffer.read()


def generate_presigned_url_from_key(key: str) -> str:
    """
    Generate a fresh presigned URL from a MinIO object key.
    This ensures URLs are always current and never expire.

    Args:
        key: MinIO object key (e.g., "interview-id/intro.mp3")

    Returns:
        Fresh presigned URL with current timestamp
    """
    settings = get_settings()
    url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": TTS_BUCKET, "Key": key},
        ExpiresIn=settings.TTS_PRESIGNED_URL_EXPIRY,
    )

    # Replace internal endpoint with external endpoint for Twilio access
    external_endpoint = settings.S3_EXTERNAL_ENDPOINT
    if external_endpoint:
        # Replace any internal endpoints with the configured external one
        url = url.replace("http://minio:9000", external_endpoint)
        url = url.replace("http://localhost:9000", external_endpoint)
        url = url.replace("https://localhost:9000", external_endpoint)

    return url


def upload_tts_to_minio(
    mp3_bytes: bytes,
    interview_id: str,
    key_suffix: str,
) -> str:
    """
    Upload MP3 to MinIO and return presigned URL.

    Args:
        mp3_bytes: MP3 file bytes
        interview_id: UUID of the interview (for path organization)
        key_suffix: Identifier (e.g., "intro", "q0", "retry_q1", "outro")

    Returns:
        Presigned URL (valid for 2 hours)
    """
    settings = get_settings()
    ensure_bucket(TTS_BUCKET)

    key = f"{interview_id}/{key_suffix}.mp3"

    s3_client.put_object(
        Bucket=TTS_BUCKET,
        Key=key,
        Body=mp3_bytes,
        ContentType="audio/mpeg",
    )
    logger.info("tts_uploaded_to_minio", key=key, size_bytes=len(mp3_bytes))

    # Generate presigned URL (valid for TTS_PRESIGNED_URL_EXPIRY seconds)
    return generate_presigned_url_from_key(key)


async def pre_generate_interview_audio(
    interview_id: str,
    candidate_name: str,
    questions: list[dict],
    voice: str,
) -> dict[str, str]:
    """
    Pre-generate all audio files needed for the interview call.
    Returns mapping of key_suffix -> presigned URL.

    Generated keys:
    - "intro": Greeting + consent reminder
    - "q{i}": Each question (i = 0-based index)
    - "retry_q{i}": Retry prompt per question
    - "off_scope_redirect": Off-scope/injection redirect message
    - "outro": Closing/thank you

    Args:
        interview_id: UUID of the interview
        candidate_name: Candidate's first name for personalization
        questions: List of question dicts from generate_interview_questions
        voice: TTS voice code

    Returns:
        Dict mapping key_suffix -> presigned URL (all audio ready for <Play> in TwiML)
    """
    urls: dict[str, str] = {}
    settings = get_settings()

    logger.info(
        "pre_generating_interview_audio",
        interview_id=interview_id,
        candidate_name=candidate_name,
        num_questions=len(questions),
        voice=voice,
    )

    # --- Intro ---
    intro_text = (
        f"Bonjour {candidate_name}. Je suis l'assistant de recrutement de l'entreprise. "
        "Merci d'avoir accepté cet entretien téléphonique. "
        "Cet appel est enregistré avec votre consentement. "
        "Je vais vous poser quelques questions. Prenez le temps de répondre complètement. "
        "Vous pouvez interrompre ma question si vous souhaitez répondre. Commençons."
    )
    intro_mp3 = await generate_tts_mp3(intro_text, voice, settings.TTS_RATE)
    urls["intro"] = upload_tts_to_minio(intro_mp3, str(interview_id), "intro")
    logger.info("intro_audio_generated", interview_id=interview_id)

    # --- Questions + Retries ---
    for i, q in enumerate(questions):
        question_text = q.get("text", str(q))
        question_number_text = f"Question {i + 1}. {question_text}"

        # Main question
        q_mp3 = await generate_tts_mp3(question_number_text, voice, settings.TTS_RATE)
        urls[f"q{i}"] = upload_tts_to_minio(q_mp3, str(interview_id), f"q{i}")
        logger.info("question_audio_generated", interview_id=interview_id, question_idx=i)

        # Retry prompt for this question
        retry_text = (
            f"Je n'ai pas bien entendu votre réponse. "
            f"Pourriez-vous répéter ? {question_text}"
        )
        retry_mp3 = await generate_tts_mp3(retry_text, voice, settings.TTS_RATE)
        urls[f"retry_q{i}"] = upload_tts_to_minio(retry_mp3, str(interview_id), f"retry_q{i}")
        logger.info("retry_audio_generated", interview_id=interview_id, question_idx=i)

    # --- Off-scope redirect (generic, reused) ---
    redirect_text = (
        "Je suis désolé, je ne peux pas répondre à cette question. "
        "Revenons à l'entretien."
    )
    redirect_mp3 = await generate_tts_mp3(redirect_text, voice, settings.TTS_RATE)
    urls["off_scope_redirect"] = upload_tts_to_minio(
        redirect_mp3, str(interview_id), "off_scope_redirect"
    )
    logger.info("off_scope_redirect_audio_generated", interview_id=interview_id)

    # --- Outro ---
    outro_text = (
        "Merci beaucoup pour vos réponses. L'entretien est maintenant terminé. "
        "Vous recevrez un retour dans les prochains jours. Bonne journée."
    )
    outro_mp3 = await generate_tts_mp3(outro_text, voice, settings.TTS_RATE)
    urls["outro"] = upload_tts_to_minio(outro_mp3, str(interview_id), "outro")
    logger.info("outro_audio_generated", interview_id=interview_id)

    logger.info("interview_audio_pre_generation_complete", interview_id=interview_id, total_urls=len(urls))

    return urls
