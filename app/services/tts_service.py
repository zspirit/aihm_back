import structlog

from app.core.config import get_settings
from app.services.storage import ensure_bucket, s3_client
from app.services.tts import synthesize as _synthesize_via_adapter

logger = structlog.get_logger()

TTS_BUCKET = "tts-audio"


async def generate_tts_mp3(
    text: str,
    voice: str | None = None,
    rate: str = "-5%",
) -> bytes:
    """Generate MP3 bytes from text.

    Delegates to the configured TTS provider via `app.services.tts` (selected
    by `settings.TTS_PROVIDER`). The `voice` argument, if provided, is passed
    through to the provider; if omitted, the provider's default voice is used
    (configured per provider in `DEFAULT_VOICE_BY_PROVIDER`).

    Kept as a thin wrapper for backwards compatibility with existing callers
    that pass `voice="fr-FR-HenriNeural"` (edge-tts voice id). When
    `TTS_PROVIDER=openai|elevenlabs`, the legacy voice id is ignored and the
    provider default is used unless `voice` matches the new provider's format.

    Args:
        text: Text to synthesize (FR).
        voice: Optional provider-specific voice id. None → default.
        rate: Speech rate ("-5%" slower, "+10%" faster). Provider-dependent.

    Returns:
        MP3 bytes ready to be saved or uploaded.
    """
    # When voice is the legacy edge-tts default and provider is not "edge",
    # ignore it (otherwise OpenAI/ElevenLabs would receive a meaningless id).
    settings = get_settings()
    if voice == "fr-FR-HenriNeural" and getattr(settings, "TTS_PROVIDER", "edge") != "edge":
        voice = None

    return await _synthesize_via_adapter(text=text, voice=voice, rate=rate)


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
    # Persona Léa + transparence IA (EU AI Act Art. 50 : annoncer qu'il s'agit
    # d'une IA, pas d'un humain). Ton chaleureux mais clair sur la nature du
    # système. Ne JAMAIS prétendre être humaine.
    intro_text = (
        f"Bonjour {candidate_name}, je suis Léa, l'assistante IA de recrutement. "
        "Cet entretien est conduit par une intelligence artificielle, "
        "et il est enregistré avec votre consentement. "
        "Je vais vous poser trois questions courtes. "
        "Prenez le temps de répondre, et si une question n'est pas claire, dites-le moi. "
        "On commence."
    )
    intro_mp3 = await generate_tts_mp3(intro_text, voice, settings.TTS_RATE)
    urls["intro"] = upload_tts_to_minio(intro_mp3, str(interview_id), "intro")
    logger.info("intro_audio_generated", interview_id=interview_id)

    # --- Questions + Retries ---
    # Transitions naturelles entre questions (vs "Question 1. ..." scripté).
    # La question elle-même est générée par Claude question_generation worker
    # avec persona Léa (formulation conversationnelle).
    transitions = [
        "Première question.",         # q0 : ouverture douce
        "Deuxième question.",          # q1 : continuité
        "Et voici la dernière.",       # q2 : signal de fin proche
        "On enchaîne.",                # q3+ : fallback si > 3 questions
        "Question suivante.",
        "Continuons.",
    ]
    for i, q in enumerate(questions):
        question_text = q.get("text", str(q))
        transition = transitions[min(i, len(transitions) - 1)]
        full_text = f"{transition} {question_text}"

        # Main question
        q_mp3 = await generate_tts_mp3(full_text, voice, settings.TTS_RATE)
        urls[f"q{i}"] = upload_tts_to_minio(q_mp3, str(interview_id), f"q{i}")
        logger.info("question_audio_generated", interview_id=interview_id, question_idx=i)

        # Retry prompt for this question — ton plus doux, pas accusateur
        retry_text = (
            f"Je n'ai pas tout à fait saisi. Pouvez-vous reformuler ou répéter ? "
            f"La question portait sur : {question_text}"
        )
        retry_mp3 = await generate_tts_mp3(retry_text, voice, settings.TTS_RATE)
        urls[f"retry_q{i}"] = upload_tts_to_minio(retry_mp3, str(interview_id), f"retry_q{i}")
        logger.info("retry_audio_generated", interview_id=interview_id, question_idx=i)

    # --- Off-scope redirect (generic, reused) ---
    redirect_text = (
        "Je préfère rester sur les questions de l'entretien. "
        "Revenons-y."
    )
    redirect_mp3 = await generate_tts_mp3(redirect_text, voice, settings.TTS_RATE)
    urls["off_scope_redirect"] = upload_tts_to_minio(
        redirect_mp3, str(interview_id), "off_scope_redirect"
    )
    logger.info("off_scope_redirect_audio_generated", interview_id=interview_id)

    # --- Confirm-reask (per question, when answer is off_scope) ---
    # Reused across all questions because the wording is generic. We append
    # the question text dynamically via TTS at runtime would defeat pre-gen,
    # so we play this generic prompt followed by the next question audio.
    for i, q in enumerate(questions):
        question_text = q.get("text", str(q))
        confirm_text = (
            "Je veux m'assurer d'avoir bien compris : "
            "souhaitez-vous vraiment donner cette réponse, "
            f"ou préférez-vous reprendre la question ? Elle portait sur : {question_text}"
        )
        confirm_mp3 = await generate_tts_mp3(confirm_text, voice, settings.TTS_RATE)
        urls[f"confirm_reask_q{i}"] = upload_tts_to_minio(
            confirm_mp3, str(interview_id), f"confirm_reask_q{i}"
        )
        logger.info("confirm_reask_audio_generated", interview_id=interview_id, question_idx=i)

    # --- Outro ---
    # Note Art. 50 : on rappelle qu'il s'agissait d'une IA (déjà annoncé en
    # intro mais utile en clôture pour ancrer la transparence dans l'expérience).
    outro_text = (
        "Voilà, c'est tout pour moi. Merci d'avoir pris le temps de répondre. "
        "Cet entretien IA va être analysé, et un recruteur humain vous recontactera "
        "dans les prochains jours avec un retour. Bonne journée."
    )
    outro_mp3 = await generate_tts_mp3(outro_text, voice, settings.TTS_RATE)
    urls["outro"] = upload_tts_to_minio(outro_mp3, str(interview_id), "outro")
    logger.info("outro_audio_generated", interview_id=interview_id)

    logger.info("interview_audio_pre_generation_complete", interview_id=interview_id, total_urls=len(urls))

    return urls
