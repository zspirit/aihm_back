from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_tenant_id, require_role
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.position import Position
from app.models.user import User
from app.schemas.application import ApplicationCreate, ApplicationDecision, ApplicationResponse

router = APIRouter(tags=["applications"])


async def _get_candidate_or_404(
    candidate_id: UUID,
    tenant_id: UUID,
    db: AsyncSession,
) -> Candidate:
    result = await db.execute(
        select(Candidate).where(
            Candidate.id == candidate_id,
            Candidate.tenant_id == tenant_id,
        )
    )
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidat introuvable")
    return candidate


@router.get(
    "/candidates/{candidate_id}/applications",
    response_model=list[ApplicationResponse],
)
async def list_candidate_applications(
    candidate_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Lister toutes les candidatures d'un candidat avec le titre du poste."""
    candidate = await _get_candidate_or_404(candidate_id, tenant_id, db)

    query = (
        select(Application, Position.title)
        .outerjoin(Position, Application.position_id == Position.id)
        .where(
            Application.candidate_id == candidate_id,
            Application.tenant_id == tenant_id,
        )
        .order_by(Application.created_at.desc())
    )
    rows = (await db.execute(query)).all()

    results = [
        ApplicationResponse(
            id=str(app.id),
            candidate_id=str(app.candidate_id),
            position_id=str(app.position_id),
            position_title=pos_title,
            match_score=app.match_score,
            match_score_explanation=app.match_score_explanation,
            pipeline_status=app.pipeline_status,
            decision=app.decision,
            decision_note=app.decision_note,
            created_at=app.created_at,
        )
        for app, pos_title in rows
    ]

    # Include the candidate's direct position if no Application exists for it
    if candidate.position_id:
        app_position_ids = {app.position_id for app, _ in rows}
        if candidate.position_id not in app_position_ids:
            pos_result = await db.execute(
                select(Position.title).where(Position.id == candidate.position_id)
            )
            pos_title = pos_result.scalar_one_or_none()
            results.insert(0, ApplicationResponse(
                id=f"direct-{candidate.id}",
                candidate_id=str(candidate.id),
                position_id=str(candidate.position_id),
                position_title=pos_title or "—",
                match_score=candidate.cv_score,
                match_score_explanation=None,
                pipeline_status=candidate.pipeline_status or "new",
                decision="pending",
                decision_note=None,
                created_at=candidate.created_at,
            ))

    return results


@router.post(
    "/candidates/{candidate_id}/applications",
    response_model=ApplicationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_application(
    candidate_id: UUID,
    body: ApplicationCreate,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Positionner un candidat sur un poste (creer une candidature)."""
    candidate = await _get_candidate_or_404(candidate_id, current_user.tenant_id, db)

    # Verifier que le poste appartient au tenant
    pos_result = await db.execute(
        select(Position).where(
            Position.id == body.position_id,
            Position.tenant_id == current_user.tenant_id,
        )
    )
    position = pos_result.scalar_one_or_none()
    if not position:
        raise HTTPException(status_code=404, detail="Poste introuvable")

    # Verifier qu'une candidature n'existe pas deja pour ce couple candidat/poste
    existing = await db.execute(
        select(Application).where(
            Application.candidate_id == candidate_id,
            Application.position_id == body.position_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Ce candidat est deja positionne sur ce poste")

    application = Application(
        tenant_id=current_user.tenant_id,
        candidate_id=candidate_id,
        position_id=UUID(body.position_id),
    )
    db.add(application)

    # Dual-write : mettre a jour candidate.position_id si pas encore renseigne
    if candidate.position_id is None:
        candidate.position_id = UUID(body.position_id)

    await db.commit()
    await db.refresh(application)

    return ApplicationResponse(
        id=str(application.id),
        candidate_id=str(application.candidate_id),
        position_id=str(application.position_id),
        position_title=position.title,
        match_score=application.match_score,
        match_score_explanation=application.match_score_explanation,
        pipeline_status=application.pipeline_status,
        decision=application.decision,
        decision_note=application.decision_note,
        created_at=application.created_at,
    )


@router.put(
    "/candidates/{candidate_id}/applications/{application_id}/decision",
    response_model=ApplicationResponse,
)
async def update_application_decision(
    candidate_id: UUID,
    application_id: UUID,
    body: ApplicationDecision,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Mettre a jour la decision sur une candidature (accepted / rejected / pending)."""
    if body.decision not in ("accepted", "rejected", "pending"):
        raise HTTPException(status_code=400, detail="Decision invalide. Valeurs acceptees : accepted, rejected, pending")

    await _get_candidate_or_404(candidate_id, current_user.tenant_id, db)

    result = await db.execute(
        select(Application).where(
            Application.id == application_id,
            Application.candidate_id == candidate_id,
            Application.tenant_id == current_user.tenant_id,
        )
    )
    application = result.scalar_one_or_none()
    if not application:
        raise HTTPException(status_code=404, detail="Candidature introuvable")

    application.decision = body.decision
    application.decision_note = body.note
    application.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(application)

    # Recuperer le titre du poste pour la reponse
    pos_result = await db.execute(
        select(Position.title).where(Position.id == application.position_id)
    )
    position_title = pos_result.scalar_one_or_none()

    return ApplicationResponse(
        id=str(application.id),
        candidate_id=str(application.candidate_id),
        position_id=str(application.position_id),
        position_title=position_title,
        match_score=application.match_score,
        match_score_explanation=application.match_score_explanation,
        pipeline_status=application.pipeline_status,
        decision=application.decision,
        decision_note=application.decision_note,
        created_at=application.created_at,
    )


@router.delete(
    "/candidates/{candidate_id}/applications/{application_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_application(
    candidate_id: UUID,
    application_id: UUID,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Supprimer une candidature."""
    await _get_candidate_or_404(candidate_id, current_user.tenant_id, db)

    result = await db.execute(
        select(Application).where(
            Application.id == application_id,
            Application.candidate_id == candidate_id,
            Application.tenant_id == current_user.tenant_id,
        )
    )
    application = result.scalar_one_or_none()
    if not application:
        raise HTTPException(status_code=404, detail="Candidature introuvable")

    await db.delete(application)
    await db.commit()
