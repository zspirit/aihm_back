"""
Batch Matching API — N*M matrix scoring for positions x candidates.
All endpoints are async. Celery workers handle the actual AI scoring.
"""
import asyncio
import json
import uuid
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session, get_db
from app.core.dependencies import get_tenant_id, require_role
from app.models.candidate import Candidate
from app.models.match_score import MatchScore, MatchSession
from app.models.position import Position
from app.models.user import User
from app.models.application import Application
from app.schemas.batch_matching import (
    AssignRequest,
    ConfirmApplicationsRequest,
    ConfirmApplicationsResponse,
    MatchSessionCreate,
    MatchSessionResponse,
    MatchSessionStatus,
    MatrixResponse,
    MatrixScore,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/matching", tags=["Batch Matching"])


@router.post("/sessions", response_model=MatchSessionResponse, status_code=202)
async def create_match_session(
    body: MatchSessionCreate,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a batch matching session for N positions x M candidates.
    If candidate_ids is null, all candidates with a parsed CV are used.
    Only recomputes missing pairs unless force_recompute=True.
    """
    tenant_id = current_user.tenant_id

    # Validate positions
    position_uuids = []
    for pid in body.position_ids:
        try:
            position_uuids.append(UUID(pid))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"position_id invalide: {pid}")

    if not position_uuids:
        raise HTTPException(status_code=400, detail="Au moins une position requise")

    # Verify positions belong to tenant
    result = await db.execute(
        select(Position.id).where(
            Position.id.in_(position_uuids),
            Position.tenant_id == tenant_id,
        )
    )
    found_positions = {row[0] for row in result.all()}
    missing = [str(pid) for pid in position_uuids if pid not in found_positions]
    if missing:
        raise HTTPException(status_code=404, detail=f"Postes introuvables: {missing}")

    # Resolve candidates
    if body.candidate_ids is not None:
        candidate_uuids = []
        for cid in body.candidate_ids:
            try:
                candidate_uuids.append(UUID(cid))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"candidate_id invalide: {cid}")

        result = await db.execute(
            select(Candidate.id).where(
                Candidate.id.in_(candidate_uuids),
                Candidate.tenant_id == tenant_id,
                Candidate.cv_parsed_data.isnot(None),
            )
        )
        candidate_uuids = [row[0] for row in result.all()]
    else:
        # All candidates with parsed CV for this tenant
        result = await db.execute(
            select(Candidate.id).where(
                Candidate.tenant_id == tenant_id,
                Candidate.cv_parsed_data.isnot(None),
            )
        )
        candidate_uuids = [row[0] for row in result.all()]

    if not candidate_uuids:
        raise HTTPException(
            status_code=400,
            detail="Aucun candidat avec CV analyse trouve",
        )

    # Compute how many pairs need scoring
    total_pairs = len(position_uuids) * len(candidate_uuids)

    # If not force_recompute, count already cached pairs
    pairs_to_compute = total_pairs
    if not body.force_recompute:
        result = await db.execute(
            select(MatchScore.candidate_id, MatchScore.position_id).where(
                MatchScore.tenant_id == tenant_id,
                MatchScore.position_id.in_(position_uuids),
                MatchScore.candidate_id.in_(candidate_uuids),
            )
        )
        cached_pairs = {(row[0], row[1]) for row in result.all()}
        all_pairs = {(cid, pid) for cid in candidate_uuids for pid in position_uuids}
        missing_pairs = all_pairs - cached_pairs
        pairs_to_compute = len(missing_pairs)

    # Create session
    session = MatchSession(
        tenant_id=tenant_id,
        user_id=current_user.id,
        position_ids=[str(pid) for pid in position_uuids],
        candidate_ids=[str(cid) for cid in candidate_uuids],
        status="pending",
        total_pairs=total_pairs,
        computed_pairs=0,
    )
    db.add(session)
    await db.flush()
    session_id = str(session.id)

    logger.info(
        "match_session_created",
        session_id=session_id,
        positions=len(position_uuids),
        candidates=len(candidate_uuids),
        total_pairs=total_pairs,
        pairs_to_compute=pairs_to_compute,
    )

    # Launch Celery task
    from app.workers.matching import compute_match_matrix
    compute_match_matrix.delay(session_id)

    return MatchSessionResponse(
        session_id=session_id,
        total_pairs=total_pairs,
        status="pending",
    )


@router.get("/sessions/{session_id}", response_model=MatchSessionStatus)
async def get_match_session(
    session_id: UUID,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Get the status of a matching session."""
    result = await db.execute(
        select(MatchSession).where(
            MatchSession.id == session_id,
            MatchSession.tenant_id == current_user.tenant_id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session de matching introuvable")

    return MatchSessionStatus(
        session_id=str(session.id),
        status=session.status,
        total_pairs=session.total_pairs,
        computed_pairs=session.computed_pairs,
        created_at=session.created_at,
        completed_at=session.completed_at,
    )


@router.get("/sessions/{session_id}/events")
async def match_session_events(
    session_id: UUID,
    request: Request,
    tenant_id: UUID = Depends(get_tenant_id),
):
    """
    SSE stream for matching session progress.
    Emits 'progress' events and a final 'done' event.
    """
    async def event_stream():
        last_computed = None
        last_status = None
        while True:
            if await request.is_disconnected():
                break
            async with async_session() as db:
                result = await db.execute(
                    select(MatchSession).where(
                        MatchSession.id == session_id,
                        MatchSession.tenant_id == tenant_id,
                    )
                )
                session = result.scalar_one_or_none()

            if not session:
                yield f"event: error\ndata: {json.dumps({'detail': 'Session introuvable'})}\n\n"
                break

            computed_changed = session.computed_pairs != last_computed
            status_changed = session.status != last_status

            if computed_changed or status_changed:
                last_computed = session.computed_pairs
                last_status = session.status
                data = {
                    "computed": session.computed_pairs,
                    "total": session.total_pairs,
                    "status": session.status,
                }
                yield f"event: progress\ndata: {json.dumps(data)}\n\n"
                if session.status in ("completed", "failed"):
                    yield f"event: done\ndata: {json.dumps({'status': session.status, 'computed': session.computed_pairs, 'total': session.total_pairs})}\n\n"
                    break

            await asyncio.sleep(2)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/matrix", response_model=MatrixResponse)
async def get_match_matrix(
    position_ids: str,
    candidate_ids: str | None = None,
    min_score: float | None = None,
    page: int = 1,
    page_size: int = 50,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """
    Read the N*M matching matrix from cache (match_scores table).
    No Claude call — purely DB reads.

    position_ids: comma-separated UUIDs (required)
    candidate_ids: comma-separated UUIDs (optional, all if omitted)
    min_score: filter candidates below this threshold (optional)
    """
    tenant_id = current_user.tenant_id

    # Parse position IDs
    try:
        pos_uuids = [UUID(pid.strip()) for pid in position_ids.split(",") if pid.strip()]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"position_ids invalides: {e}")

    if not pos_uuids:
        raise HTTPException(status_code=400, detail="position_ids requis")

    # Load positions metadata
    result = await db.execute(
        select(Position).where(
            Position.id.in_(pos_uuids),
            Position.tenant_id == tenant_id,
        )
    )
    positions_map = {p.id: p for p in result.scalars().all()}
    positions_data = [
        {
            "id": str(pos.id),
            "title": pos.title,
            "seniority_level": pos.seniority_level,
        }
        for pos in positions_map.values()
    ]

    # Parse candidate IDs if provided
    cand_uuids: list[UUID] | None = None
    if candidate_ids:
        try:
            cand_uuids = [UUID(cid.strip()) for cid in candidate_ids.split(",") if cid.strip()]
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"candidate_ids invalides: {e}")

    # Build scores query
    scores_query = select(MatchScore).where(
        MatchScore.tenant_id == tenant_id,
        MatchScore.position_id.in_(pos_uuids),
    )
    if cand_uuids:
        scores_query = scores_query.where(MatchScore.candidate_id.in_(cand_uuids))
    if min_score is not None:
        scores_query = scores_query.where(MatchScore.score >= min_score)

    result = await db.execute(scores_query)
    all_scores = result.scalars().all()

    # Get unique candidate IDs from scores
    cand_ids_in_scores = list({s.candidate_id for s in all_scores})

    # Paginate candidates
    offset = (page - 1) * page_size
    paginated_cand_ids = cand_ids_in_scores[offset: offset + page_size]

    # Load candidate metadata
    candidates_data = []
    if paginated_cand_ids:
        result = await db.execute(
            select(Candidate).where(
                Candidate.id.in_(paginated_cand_ids),
                Candidate.tenant_id == tenant_id,
            )
        )
        candidates_list = result.scalars().all()
        candidates_data = [
            {
                "id": str(c.id),
                "name": c.name,
                "email": c.email,
                "cv_score": c.cv_score,
                "pipeline_status": c.pipeline_status,
                "position_id": str(c.position_id),
            }
            for c in candidates_list
        ]

    # Filter scores to paginated candidates
    paginated_cand_set = {UUID(c["id"]) for c in candidates_data}
    matrix_scores = [
        MatrixScore(
            candidate_id=str(s.candidate_id),
            position_id=str(s.position_id),
            score=s.score,
            reasons=s.reasons,
        )
        for s in all_scores
        if s.candidate_id in paginated_cand_set
    ]

    return MatrixResponse(
        positions=positions_data,
        candidates=candidates_data,
        scores=matrix_scores,
        total_candidates=len(cand_ids_in_scores),
    )


@router.post("/assign")
async def assign_candidates(
    body: AssignRequest,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """
    Assigner des candidats à des postes via Applications.
    Crée une Application (lien candidat <-> poste) au lieu de dupliquer le candidat.
    Skip si une Application existe déjà pour ce couple.
    """
    tenant_id = current_user.tenant_id

    if not body.assignments:
        raise HTTPException(status_code=400, detail="Aucune assignation fournie")

    results = []
    for assignment in body.assignments:
        candidate_id_str = assignment.get("candidate_id")
        position_id_str = assignment.get("position_id")

        if not candidate_id_str or not position_id_str:
            results.append({"error": "candidate_id et position_id requis", "assignment": assignment})
            continue

        try:
            candidate_uuid = UUID(candidate_id_str)
            position_uuid = UUID(position_id_str)
        except ValueError:
            results.append({"error": "UUID invalide", "assignment": assignment})
            continue

        # Vérifier que le poste appartient au tenant
        result = await db.execute(
            select(Position).where(
                Position.id == position_uuid,
                Position.tenant_id == tenant_id,
            )
        )
        target_position = result.scalar_one_or_none()
        if not target_position:
            results.append({"error": "Poste introuvable", "position_id": position_id_str})
            continue

        # Vérifier que le candidat appartient au tenant
        result = await db.execute(
            select(Candidate).where(
                Candidate.id == candidate_uuid,
                Candidate.tenant_id == tenant_id,
            )
        )
        candidate = result.scalar_one_or_none()
        if not candidate:
            results.append({"error": "Candidat introuvable", "candidate_id": candidate_id_str})
            continue

        # Vérifier si une Application existe déjà pour ce couple
        result = await db.execute(
            select(Application.id).where(
                Application.candidate_id == candidate_uuid,
                Application.position_id == position_uuid,
                Application.tenant_id == tenant_id,
            )
        )
        if result.scalar_one_or_none():
            results.append({
                "status": "skipped",
                "reason": "application_exists",
                "candidate_id": candidate_id_str,
                "position_id": position_id_str,
            })
            continue

        # Récupérer le MatchScore en cache si disponible
        result = await db.execute(
            select(MatchScore).where(
                MatchScore.candidate_id == candidate_uuid,
                MatchScore.position_id == position_uuid,
                MatchScore.tenant_id == tenant_id,
            )
        )
        cached_score = result.scalar_one_or_none()

        # Créer l'Application
        application = Application(
            tenant_id=tenant_id,
            candidate_id=candidate_uuid,
            position_id=position_uuid,
            match_score=cached_score.score if cached_score else None,
            match_score_explanation=cached_score.reasons if cached_score else None,
            pipeline_status="new",
        )
        db.add(application)

        # Dual-write : mettre à jour candidate.position_id si première application
        if candidate.position_id is None:
            candidate.position_id = position_uuid

        await db.flush()

        logger.info(
            "application_created_from_assign",
            candidate_id=candidate_id_str,
            position_id=position_id_str,
            application_id=str(application.id),
            has_score=cached_score is not None,
        )
        results.append({
            "status": "assigned",
            "candidate_id": candidate_id_str,
            "position_id": position_id_str,
            "application_id": str(application.id),
            "match_score": cached_score.score if cached_score else None,
        })

    await db.commit()
    return {"results": results}


@router.post(
    "/confirm-applications",
    response_model=ConfirmApplicationsResponse,
    status_code=201,
)
async def confirm_applications(
    body: ConfirmApplicationsRequest,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """
    Confirmer des candidatures après matching.
    Pour chaque paire (candidate_id, position_id) :
    - Cherche le MatchScore en cache
    - Crée une Application avec le score
    - Skip si l'Application existe déjà
    """
    tenant_id = current_user.tenant_id

    if not body.pairs:
        raise HTTPException(status_code=400, detail="Aucune paire fournie")

    created = 0
    skipped = 0

    for pair in body.pairs:
        candidate_id_str = pair.get("candidate_id")
        position_id_str = pair.get("position_id")

        if not candidate_id_str or not position_id_str:
            continue

        try:
            candidate_uuid = UUID(candidate_id_str)
            position_uuid = UUID(position_id_str)
        except ValueError:
            continue

        # Vérifier que le candidat et le poste appartiennent au tenant
        result = await db.execute(
            select(Candidate.id).where(
                Candidate.id == candidate_uuid,
                Candidate.tenant_id == tenant_id,
            )
        )
        if not result.scalar_one_or_none():
            continue

        result = await db.execute(
            select(Position.id).where(
                Position.id == position_uuid,
                Position.tenant_id == tenant_id,
            )
        )
        if not result.scalar_one_or_none():
            continue

        # Vérifier si l'Application existe déjà
        result = await db.execute(
            select(Application.id).where(
                Application.candidate_id == candidate_uuid,
                Application.position_id == position_uuid,
                Application.tenant_id == tenant_id,
            )
        )
        if result.scalar_one_or_none():
            skipped += 1
            continue

        # Récupérer le MatchScore en cache
        result = await db.execute(
            select(MatchScore).where(
                MatchScore.candidate_id == candidate_uuid,
                MatchScore.position_id == position_uuid,
                MatchScore.tenant_id == tenant_id,
            )
        )
        cached_score = result.scalar_one_or_none()

        # Créer l'Application
        application = Application(
            tenant_id=tenant_id,
            candidate_id=candidate_uuid,
            position_id=position_uuid,
            match_score=cached_score.score if cached_score else None,
            match_score_explanation=cached_score.reasons if cached_score else None,
            pipeline_status="new",
        )
        db.add(application)

        # Dual-write : mettre à jour candidate.position_id si première application
        result = await db.execute(
            select(Candidate).where(
                Candidate.id == candidate_uuid,
                Candidate.tenant_id == tenant_id,
            )
        )
        candidate = result.scalar_one_or_none()
        if candidate and candidate.position_id is None:
            candidate.position_id = position_uuid

        created += 1

    await db.commit()

    logger.info(
        "confirm_applications_done",
        tenant_id=str(tenant_id),
        created=created,
        skipped=skipped,
    )

    return ConfirmApplicationsResponse(created=created, skipped=skipped)
