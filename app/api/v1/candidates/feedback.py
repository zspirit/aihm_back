"""Endpoints feedback candidat post-evaluation."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.candidate import Candidate
from app.models.user import User
from app.services.audit import log_action

router = APIRouter(tags=["candidates"])


@router.post("/candidates/{candidate_id}/feedback/generate")
async def generate_feedback(
    candidate_id: UUID,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Genere le feedback candidat via Claude."""
    from starlette.concurrency import run_in_threadpool

    from app.services.candidate_feedback import generate_candidate_feedback

    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    if not candidate.cv_parsed_data:
        raise HTTPException(
            status_code=400,
            detail="CV non analyse. Lancez d'abord l'analyse du CV.",
        )

    # Build candidate dict
    candidate_dict = {
        "name": candidate.name,
        "cv_parsed_data": candidate.cv_parsed_data,
        "cv_score": candidate.cv_score,
        "profile_score": candidate.profile_score,
    }

    # Load position if linked
    position_data = None
    if candidate.position_id:
        from app.models.position import Position

        pos_result = await db.execute(
            select(Position).where(Position.id == candidate.position_id)
        )
        position = pos_result.scalar_one_or_none()
        if position:
            position_data = {
                "title": position.title,
                "required_skills": position.required_skills,
            }

    # Load latest analysis if available
    analysis_data = None
    from app.models.interview import Interview
    from app.models.analysis import Analysis

    interview_result = await db.execute(
        select(Interview)
        .where(
            Interview.candidate_id == candidate_id,
            Interview.tenant_id == current_user.tenant_id,
            Interview.status == "completed",
        )
        .order_by(Interview.ended_at.desc())
        .limit(1)
    )
    interview = interview_result.scalar_one_or_none()
    if interview:
        analysis_result = await db.execute(
            select(Analysis).where(Analysis.interview_id == interview.id)
        )
        analysis = analysis_result.scalar_one_or_none()
        if analysis:
            analysis_data = {
                "scores": analysis.scores,
                "skills_extracted": analysis.skills_extracted,
                "communication_indicators": analysis.communication_indicators,
                "score_explanations": analysis.score_explanations,
            }

    try:
        feedback = await run_in_threadpool(
            generate_candidate_feedback,
            candidate_dict,
            position_data,
            analysis_data,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Erreur de parsing de la reponse Claude : {e}",
        )
    except Exception:
        import structlog

        _log = structlog.get_logger()
        _log.error(
            "generate_feedback_claude_error",
            candidate_id=str(candidate_id),
        )
        raise HTTPException(
            status_code=502,
            detail="Erreur lors de l'appel a Claude. Veuillez reessayer.",
        )

    # Store in DB
    candidate.feedback_json = feedback
    await log_action(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="generate_feedback",
        entity_type="candidate",
        entity_id=str(candidate_id),
    )
    await db.commit()
    await db.refresh(candidate)

    return {
        "candidate_id": str(candidate.id),
        "feedback": feedback,
    }


@router.get("/candidates/{candidate_id}/feedback")
async def get_feedback(
    candidate_id: UUID,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Retourne le feedback deja genere."""
    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    if not candidate.feedback_json:
        raise HTTPException(status_code=404, detail="Aucun feedback genere pour ce candidat")

    return {
        "candidate_id": str(candidate.id),
        "feedback": candidate.feedback_json,
        "sent_at": candidate.feedback_sent_at.isoformat() if candidate.feedback_sent_at else None,
    }


@router.post("/candidates/{candidate_id}/feedback/send")
async def send_feedback(
    candidate_id: UUID,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Envoie le feedback par email au candidat."""
    from datetime import datetime, timezone

    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")

    if not candidate.feedback_json:
        raise HTTPException(status_code=400, detail="Aucun feedback genere. Generez-le d'abord.")

    if not candidate.email:
        raise HTTPException(status_code=400, detail="Le candidat n'a pas d'adresse email.")

    # Load tenant name and position title for the email
    from app.models.tenant import Tenant
    from app.models.position import Position

    tenant = await db.get(Tenant, candidate.tenant_id)
    position_title = ""
    if candidate.position_id:
        position = await db.get(Position, candidate.position_id)
        if position:
            position_title = position.title

    # Render email
    from app.services.email import render

    feedback = candidate.feedback_json
    html = render(
        "email/candidate_feedback.html",
        candidate_name=candidate.name,
        tenant_name=tenant.name if tenant else "L'entreprise",
        position_title=position_title,
        greeting=feedback.get("greeting", "Bonjour,"),
        strengths=feedback.get("strengths", []),
        improvements=feedback.get("improvements", []),
        general_advice=feedback.get("general_advice", ""),
        closing=feedback.get("closing", ""),
    )

    # Send via Celery worker
    from app.workers.notifications import send_email

    send_email.delay(
        candidate.email,
        f"Votre feedback - {position_title} - {tenant.name if tenant else ''}",
        html,
    )

    candidate.feedback_sent_at = datetime.now(timezone.utc)
    await log_action(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action="send_feedback",
        entity_type="candidate",
        entity_id=str(candidate_id),
    )
    await db.commit()

    return {
        "status": "sent",
        "candidate_id": str(candidate.id),
        "sent_to": candidate.email,
    }
