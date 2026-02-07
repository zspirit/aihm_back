import json
import structlog
from celery import shared_task

logger = structlog.get_logger()


@shared_task(name="report.generate", bind=True, max_retries=3)
def generate_report(self, interview_id: str):
    logger.info("report_generation_start", interview_id=interview_id)

    from app.workers.cv_processing import get_sync_session

    session = get_sync_session()
    try:
        from uuid import UUID

        from sqlalchemy import select

        from app.models.analysis import Analysis
        from app.models.candidate import Candidate
        from app.models.interview import Interview
        from app.models.position import Position
        from app.models.report import Report
        from app.models.transcription import Transcription

        interview = session.get(Interview, UUID(interview_id))
        if not interview:
            return

        candidate = session.get(Candidate, interview.candidate_id)
        position = session.get(Position, interview.position_id)

        analysis_result = session.execute(
            select(Analysis).where(Analysis.interview_id == interview.id)
        )
        analysis = analysis_result.scalar_one_or_none()

        trans_result = session.execute(
            select(Transcription).where(Transcription.interview_id == interview.id)
        )
        transcription = trans_result.scalar_one_or_none()

        report_content = build_report(candidate, position, interview, analysis, transcription)

        report = Report(
            candidate_id=candidate.id,
            interview_id=interview.id,
            content=report_content,
        )
        session.add(report)
        session.commit()

        logger.info("report_generation_done", interview_id=interview_id)

    except Exception as e:
        session.rollback()
        logger.error("report_generation_error", interview_id=interview_id, error=str(e))
        raise self.retry(exc=e, countdown=30)
    finally:
        session.close()


def build_report(candidate, position, interview, analysis, transcription) -> dict:
    from anthropic import Anthropic
    from app.core.config import get_settings

    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    analysis_data = {}
    if analysis:
        analysis_data = {
            "scores": analysis.scores,
            "score_explanations": analysis.score_explanations,
            "skills_extracted": analysis.skills_extracted,
            "experience_examples": analysis.experience_examples,
            "communication_indicators": analysis.communication_indicators,
        }

    trans_text = transcription.full_text if transcription else ""

    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=2000,
        messages=[
            {
                "role": "user",
                "content": f"""Genere un rapport d'evaluation structure pour ce candidat.
Le rapport doit etre professionnel, factuel, et imprimable.

CANDIDAT: {candidate.name}
POSTE: {position.title} ({position.seniority_level})
DUREE ENTRETIEN: {interview.duration_seconds or 0} secondes
DATE: {interview.ended_at or interview.created_at}

ANALYSE:
{json.dumps(analysis_data, ensure_ascii=False)[:2500]}

REGLES STRICTES:
- Aucune recommandation d'embauche (PAS de "nous recommandons", "ce candidat devrait etre...")
- Basé uniquement sur des signaux observables
- PAS d'inference de personnalite ou d'emotion
- Le rapport INFORME, le recruteur DECIDE

Format JSON:
{{
    "title": "Rapport d'evaluation - [Nom candidat]",
    "position": "{position.title}",
    "date": "...",
    "summary": "Resume en 3-4 phrases des points cles, factuel",
    "scores": {{
        "global": 0,
        "technical": 0,
        "experience": 0,
        "communication": 0
    }},
    "strengths": [
        "Point fort 1 avec evidence",
        "Point fort 2 avec evidence"
    ],
    "areas_to_explore": [
        "Element a approfondir 1",
        "Element a approfondir 2"
    ],
    "skills_assessment": [
        {{"skill": "...", "level": "...", "evidence": "..."}}
    ],
    "key_quotes": [
        "Verbatim pertinent 1",
        "Verbatim pertinent 2"
    ],
    "metadata": {{
        "interview_duration": "{interview.duration_seconds or 0}s",
        "questions_count": {len(interview.questions_asked or [])},
        "generated_by": "AIHM AI Assistant",
        "disclaimer": "Ce rapport est genere par IA a titre informatif. Il ne constitue pas une recommandation d'embauche."
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
            "title": f"Rapport - {candidate.name}",
            "position": position.title,
            "summary": "Erreur lors de la generation du rapport",
            "scores": analysis.scores if analysis else {},
            "metadata": {"generated_by": "AIHM", "error": True},
        }
