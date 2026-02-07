from uuid import UUID

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import Response
from sqlalchemy import select

from app.core.database import async_session
from app.models.candidate import Candidate
from app.models.interview import Interview

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/twilio/status")
async def twilio_status_callback(
    request: Request,
    CallSid: str = Form(""),
    CallStatus: str = Form(""),
    CallDuration: str = Form("0"),
):
    from app.workers.telephony import handle_call_status

    handle_call_status.delay(CallSid, CallStatus, int(CallDuration or 0))
    return {"status": "ok"}


@router.post("/twilio/recording")
async def twilio_recording_callback(
    request: Request,
    CallSid: str = Form(""),
    RecordingUrl: str = Form(""),
    RecordingSid: str = Form(""),
    RecordingDuration: str = Form("0"),
):
    from app.workers.telephony import handle_recording_ready

    handle_recording_ready.delay(CallSid, RecordingUrl, RecordingSid, int(RecordingDuration or 0))
    return {"status": "ok"}


@router.post("/twilio/voice")
async def twilio_voice_handler(
    request: Request,
    interview_id: str = Query(""),
):
    """TwiML voice handler — returns XML instructions for the interview call."""
    questions = []
    candidate_name = "candidat"

    if interview_id:
        async with async_session() as db:
            result = await db.execute(
                select(Interview).where(Interview.id == UUID(interview_id))
            )
            interview = result.scalar_one_or_none()
            if interview and interview.questions_asked:
                questions = interview.questions_asked
                cand_result = await db.execute(
                    select(Candidate).where(Candidate.id == interview.candidate_id)
                )
                candidate = cand_result.scalar_one_or_none()
                if candidate:
                    candidate_name = candidate.name

    twiml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<Response>",
        '  <Say language="fr-FR" voice="Polly.Lea">',
        f"    Bonjour {candidate_name}. Je suis l'assistant de recrutement.",
        "    Merci d'avoir accepte cet entretien telephonique.",
        "    Je vais vous poser quelques questions. Prenez le temps de repondre apres chaque question.",
        "    L'appel est enregistre pour analyse. Commençons.",
        "  </Say>",
        '  <Pause length="2"/>',
    ]

    for i, q in enumerate(questions):
        question_text = q.get("text", q) if isinstance(q, dict) else str(q)
        pause_duration = q.get("expected_duration_seconds", 45) if isinstance(q, dict) else 45
        twiml_parts.extend([
            f'  <Say language="fr-FR" voice="Polly.Lea">',
            f"    Question {i + 1}. {question_text}",
            "  </Say>",
            f'  <Pause length="{pause_duration}"/>',
        ])

    twiml_parts.extend([
        '  <Say language="fr-FR" voice="Polly.Lea">',
        "    Merci beaucoup pour vos reponses. L'entretien est maintenant termine.",
        "    Vous recevrez un retour prochainement. Bonne journee.",
        "  </Say>",
        "</Response>",
    ])

    return Response(content="\n".join(twiml_parts), media_type="application/xml")
