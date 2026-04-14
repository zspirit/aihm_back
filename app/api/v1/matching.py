import asyncio
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_module, require_role
from app.models.candidate import Candidate
from app.models.position import Position
from app.models.user import User
from app.schemas.matching import AddFromMatchRequest, MatchRequest, MatchResponse, MatchResult
from app.services.matching import ai_score_matches, pre_filter_candidates

logger = structlog.get_logger()
router = APIRouter(prefix="/positions", tags=["Matching"])


@router.post("/{position_id}/match", response_model=MatchResponse, dependencies=[require_module("matching_nm")])
async def match_candidates_for_position(
    position_id: UUID,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """
    Find matching candidates from other positions for a specific position.
    """
    # Load target position
    result = await db.execute(
        select(Position).where(
            Position.id == position_id,
            Position.tenant_id == current_user.tenant_id,
        )
    )
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status_code=404, detail="Poste introuvable")

    # Pre-filter candidates
    candidates = await pre_filter_candidates(
        db=db,
        tenant_id=current_user.tenant_id,
        exclude_position_id=position_id,
        required_skills=position.required_skills,
        seniority_level=position.seniority_level,
        limit=30,
    )

    if not candidates:
        return MatchResponse(matches=[])

    # AI scoring
    position_data = {
        "title": position.title,
        "description": position.description,
        "required_skills": position.required_skills,
        "seniority_level": position.seniority_level,
    }

    try:
        matches = await asyncio.to_thread(ai_score_matches, candidates, position_data, 20)
        match_results = [MatchResult(**m) for m in matches]
        return MatchResponse(matches=match_results)
    except Exception as e:
        logger.error("match_endpoint_error", error=str(e), error_type=type(e).__name__)
        raise HTTPException(status_code=502, detail=f"Erreur lors du matching: {str(e)}")


@router.post("/match", response_model=MatchResponse, dependencies=[require_module("matching_nm")])
async def match_candidates_with_criteria(
    request: MatchRequest,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """
    Find matching candidates based on custom criteria (not tied to a specific position).
    """
    # Pre-filter candidates
    candidates = await pre_filter_candidates(
        db=db,
        tenant_id=current_user.tenant_id,
        exclude_position_id=None,
        required_skills=request.required_skills if request.required_skills else None,
        seniority_level=request.seniority_level,
        limit=30,
    )

    if not candidates:
        return MatchResponse(matches=[])

    # AI scoring
    position_data = {
        "title": request.title,
        "description": request.description,
        "required_skills": request.required_skills,
        "seniority_level": request.seniority_level,
    }

    matches = await asyncio.to_thread(ai_score_matches, candidates, position_data, request.limit)

    match_results = [MatchResult(**m) for m in matches]

    return MatchResponse(matches=match_results)


@router.post("/{position_id}/candidates/add-from-match")
async def add_candidates_from_match(
    position_id: UUID,
    request: AddFromMatchRequest,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """
    Add candidates from matching results to a target position.
    Copies candidate data and triggers CV processing.
    """
    # Verify target position exists
    result = await db.execute(
        select(Position).where(
            Position.id == position_id,
            Position.tenant_id == current_user.tenant_id,
        )
    )
    target_position = result.scalar_one_or_none()
    if not target_position:
        raise HTTPException(status_code=404, detail="Poste introuvable")

    # Load all source candidates
    candidate_ids = [UUID(cid) for cid in request.candidate_ids]
    result = await db.execute(
        select(Candidate).where(
            Candidate.id.in_(candidate_ids),
            Candidate.tenant_id == current_user.tenant_id,
        )
    )
    source_candidates = result.scalars().all()

    # Check for existing emails in target position
    result = await db.execute(
        select(Candidate.email).where(
            Candidate.position_id == position_id,
            Candidate.email.isnot(None),
        )
    )
    existing_emails = {row[0] for row in result.all()}

    added = 0
    skipped = 0
    new_candidate_ids = []

    for source in source_candidates:
        # Skip if email already exists in target position
        if source.email and source.email in existing_emails:
            logger.info(
                "candidate_skip_duplicate",
                email=source.email,
                position_id=str(position_id),
            )
            skipped += 1
            continue

        # Create new candidate in target position
        new_candidate = Candidate(
            tenant_id=current_user.tenant_id,
            position_id=position_id,
            name=source.name,
            email=source.email,
            phone=source.phone,
            cv_file_path=source.cv_file_path,
            cv_parsed_data=source.cv_parsed_data,
            # Do NOT copy cv_score - needs re-scoring against new position
            pipeline_status="new",
        )
        db.add(new_candidate)
        await db.flush()

        new_candidate_ids.append(str(new_candidate.id))
        added += 1

        logger.info(
            "candidate_added_from_match",
            source_candidate_id=str(source.id),
            new_candidate_id=str(new_candidate.id),
            position_id=str(position_id),
        )

    # Trigger CV processing for new candidates
    if new_candidate_ids:
        try:
            from app.workers.cv_processing import process_cv

            for candidate_id in new_candidate_ids:
                process_cv.delay(candidate_id, str(position_id))
        except Exception:
            # Celery unavailable — run inline
            import asyncio
            from starlette.concurrency import run_in_threadpool

            pid = str(position_id)
            cids = list(new_candidate_ids)

            async def _score_inline():
                for cid in cids:
                    try:
                        from app.workers.cv_processing import process_cv as _pvc
                        await run_in_threadpool(_pvc, cid, pid)
                    except Exception:
                        pass

            asyncio.create_task(_score_inline())

    return {
        "status": "ok",
        "added": added,
        "skipped": skipped,
        "total_requested": len(request.candidate_ids),
    }
