"""Worker de generation et envoi du feedback candidat post-rapport."""

from datetime import datetime, timezone

import structlog
from celery import shared_task

from app.workers.base import worker_session

logger = structlog.get_logger()


@shared_task(name="feedback.generate_and_send")
def generate_and_send_feedback(candidate_id_str: str, interview_id_str: str):
    """Generate candidate feedback after interview report is committed."""
    with worker_session() as session:
        from uuid import UUID

        from app.models.candidate import Candidate
        from app.models.interview import Interview
        from app.models.position import Position
        from app.services.candidate_feedback import generate_candidate_feedback

        candidate = session.get(Candidate, UUID(candidate_id_str))
        if not candidate:
            logger.error("feedback_candidate_not_found", candidate_id=candidate_id_str)
            return

        interview = session.get(Interview, UUID(interview_id_str))
        if not interview:
            logger.error("feedback_interview_not_found", interview_id=interview_id_str)
            return

        position = session.get(Position, interview.position_id) if interview.position_id else None

        # Build analysis dict from Analysis table
        analysis_data = None
        from sqlalchemy import select
        from app.models.analysis import Analysis

        analysis_result = session.execute(
            select(Analysis).where(Analysis.interview_id == interview.id)
        )
        analysis_obj = analysis_result.scalar_one_or_none()
        if analysis_obj:
            analysis_data = {
                "scores": analysis_obj.scores,
                "skills_extracted": analysis_obj.skills_extracted,
                "communication_indicators": analysis_obj.communication_indicators,
                "score_explanations": analysis_obj.score_explanations,
            }

        # Build candidate dict for the service
        candidate_dict = {
            "name": candidate.name,
            "cv_parsed_data": candidate.cv_parsed_data,
            "cv_score": candidate.cv_score,
            "profile_score": candidate.profile_score,
        }

        position_dict = None
        if position:
            position_dict = {
                "title": position.title,
                "required_skills": position.required_skills,
            }

        logger.info(
            "feedback_generation_start",
            candidate_id=candidate_id_str,
            interview_id=interview_id_str,
        )

        feedback = generate_candidate_feedback(candidate_dict, position_dict, analysis_data)

        candidate.feedback_json = feedback
        candidate.feedback_sent_at = datetime.now(timezone.utc)
        session.commit()

        logger.info(
            "feedback_stored",
            candidate_id=candidate_id_str,
            interview_id=interview_id_str,
        )

        # Send email if candidate has an email address
        if candidate.email:
            from app.workers.notifications import send_email

            subject = "Votre feedback d'entretien AIHM"
            html_body = _build_feedback_email(feedback, candidate.name)
            send_email.delay(candidate.email, subject, html_body)
            logger.info("feedback_email_queued", candidate_id=candidate_id_str, to=candidate.email)


def _build_feedback_email(feedback: dict, candidate_name: str) -> str:
    """Build simple HTML email body from feedback data."""
    greeting = feedback.get("greeting", f"Bonjour {candidate_name},")
    strengths_html = ""
    for s in feedback.get("strengths", []):
        strengths_html += f"<li><strong>{s.get('title', '')}</strong>: {s.get('detail', '')}</li>"

    improvements_html = ""
    for imp in feedback.get("improvements", []):
        improvements_html += (
            f"<li><strong>{imp.get('title', '')}</strong>: {imp.get('detail', '')}"
            f"<br><em>Conseil : {imp.get('advice', '')}</em></li>"
        )

    general = feedback.get("general_advice", "")
    closing = feedback.get("closing", "")

    return f"""<html><body>
<p>{greeting}</p>
<h3>Points forts</h3>
<ul>{strengths_html}</ul>
<h3>Axes d'amelioration</h3>
<ul>{improvements_html}</ul>
<p>{general}</p>
<p>{closing}</p>
<hr>
<p><small>Ce feedback a ete genere par IA a titre informatif.</small></p>
</body></html>"""
