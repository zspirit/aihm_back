import json

import structlog
from celery import shared_task

logger = structlog.get_logger()


@shared_task(name="analysis.analyze", bind=True, max_retries=3)
def analyze_interview(self, interview_id: str):
    logger.info("analysis_start", interview_id=interview_id)

    from app.workers.cv_processing import get_sync_session

    session = get_sync_session()
    try:
        from uuid import UUID

        from sqlalchemy import select

        from app.models.analysis import Analysis
        from app.models.candidate import Candidate
        from app.models.interview import Interview
        from app.models.position import Position
        from app.models.transcription import Transcription

        interview = session.get(Interview, UUID(interview_id))
        if not interview:
            return

        trans_result = session.execute(
            select(Transcription).where(Transcription.interview_id == interview.id)
        )
        transcription = trans_result.scalar_one_or_none()
        if not transcription:
            logger.warning("analysis_skip_no_transcription", interview_id=interview_id)
            return

        candidate = session.get(Candidate, interview.candidate_id)
        position = session.get(Position, interview.position_id)

        analysis_result = run_analysis(transcription, position, candidate)

        analysis = Analysis(
            interview_id=interview.id,
            skills_extracted=analysis_result.get("skills_extracted"),
            experience_examples=analysis_result.get("experience_examples"),
            communication_indicators=analysis_result.get("communication_indicators"),
            scores=analysis_result.get("scores"),
            score_explanations=analysis_result.get("score_explanations"),
        )
        session.add(analysis)

        candidate.pipeline_status = "evaluated"
        session.commit()

        logger.info("analysis_done", interview_id=interview_id)

        # Trigger report generation
        from app.workers.report_generation import generate_report

        generate_report.delay(interview_id)

    except Exception as e:
        session.rollback()
        logger.error("analysis_error", interview_id=interview_id, error=str(e))
        raise self.retry(exc=e, countdown=30)
    finally:
        session.close()


def run_analysis(transcription, position, candidate) -> dict:
    from anthropic import Anthropic

    from app.core.config import get_settings

    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    cv_data = candidate.cv_parsed_data or {}
    segments = transcription.segments or {}

    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=2000,
        messages=[
            {
                "role": "user",
                "content": f"""Analyse cet entretien telephonique. Reponds UNIQUEMENT en JSON.

FICHE DE POSTE:
- Titre: {position.title}
- Competences requises: {json.dumps(position.required_skills)}
- Niveau: {position.seniority_level}

CV DU CANDIDAT:
{json.dumps(cv_data, ensure_ascii=False)[:1000]}

TRANSCRIPTION DE L'ENTRETIEN:
{transcription.full_text[:3000]}

SEGMENTS PAR QUESTION:
{json.dumps(segments, ensure_ascii=False)[:2000]}

REGLES STRICTES (GUARDRAILS):
- Analyse basee UNIQUEMENT sur les signaux observables dans les reponses
- PAS d'inference de personnalite, d'emotion ou de motivation
- PAS de recommandation d'embauche (l'IA assiste, l'humain decide)
- PAS d'inference d'attributs proteges (genre, age, origine, etc.)
- Chaque score DOIT etre justifie par des elements factuels de la transcription
- Les indicateurs de communication mesurent: clarte, structure, fluidite (PAS les emotions)

Format JSON:
{{
    "skills_extracted": [
        {{"skill": "nom", "evidence": "citation ou element de la transcription", "level": "debutant|intermediaire|avance"}}
    ],
    "experience_examples": [
        {{"context": "situation decrite", "actions": "ce que le candidat a fait", "result": "resultat mentionne"}}
    ],
    "communication_indicators": {{
        "clarity": {{"score": 75, "evidence": "..."}},
        "structure": {{"score": 70, "evidence": "..."}},
        "fluency": {{"score": 80, "evidence": "..."}}
    }},
    "scores": {{
        "technical": 70,
        "experience": 75,
        "communication": 75,
        "global": 73
    }},
    "score_explanations": {{
        "technical": "justification basee sur les reponses...",
        "experience": "justification...",
        "communication": "justification...",
        "global": "moyenne ponderee expliquee..."
    }}
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
        return {
            "scores": {"technical": 0, "experience": 0, "communication": 0, "global": 0},
            "score_explanations": {"error": "Analysis failed"},
        }
