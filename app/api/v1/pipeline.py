"""Pipeline board endpoints — kanban view of candidates by status."""

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_tenant_id
from app.models.candidate import Candidate
from app.models.position import Position
from app.models.user import User
from app.schemas.pipeline import (
    PIPELINE_LABELS,
    PIPELINE_STATUSES,
    PipelineBoardResponse,
    PipelineCandidateItem,
    PipelineColumn,
    PipelineMoveRequest,
    PipelineMoveResponse,
)
from app.services.audit import log_action

logger = structlog.get_logger()

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

MAX_PER_COLUMN = 50


@router.get("/board", response_model=PipelineBoardResponse)
async def get_pipeline_board(
    position_id: str | None = Query(None, description="Filter by position"),
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Return candidates grouped by pipeline status for kanban board."""

    columns: list[PipelineColumn] = []

    for status in PIPELINE_STATUSES:
        query = (
            select(
                Candidate.id,
                Candidate.name,
                Candidate.email,
                Candidate.cv_score,
                Candidate.pipeline_status,
                Candidate.created_at,
                Position.title.label("position_title"),
            )
            .outerjoin(Position, Candidate.position_id == Position.id)
            .where(Candidate.tenant_id == tenant_id)
            .where(Candidate.pipeline_status == status)
            .order_by(Candidate.created_at.desc())
            .limit(MAX_PER_COLUMN)
        )

        if position_id:
            query = query.where(Candidate.position_id == position_id)

        count_query = (
            select(func.count())
            .select_from(Candidate)
            .where(Candidate.tenant_id == tenant_id)
            .where(Candidate.pipeline_status == status)
        )
        if position_id:
            count_query = count_query.where(Candidate.position_id == position_id)

        result = await db.execute(query)
        rows = result.all()

        count_result = await db.execute(count_query)
        total = count_result.scalar() or 0

        candidates = [
            PipelineCandidateItem(
                id=str(row.id),
                name=row.name,
                email=row.email,
                position_title=row.position_title,
                cv_score=row.cv_score,
                pipeline_status=row.pipeline_status,
                updated_at=row.created_at,
            )
            for row in rows
        ]

        columns.append(
            PipelineColumn(
                status=status,
                label=PIPELINE_LABELS[status],
                candidates=candidates,
                count=total,
            )
        )

    return PipelineBoardResponse(columns=columns)


@router.patch("/move", response_model=PipelineMoveResponse)
async def move_candidate(
    body: PipelineMoveRequest,
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Move a candidate to a new pipeline status."""

    if body.new_status not in PIPELINE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{body.new_status}'. Must be one of: {', '.join(PIPELINE_STATUSES)}",
        )

    result = await db.execute(
        select(Candidate)
        .where(Candidate.id == body.candidate_id)
        .where(Candidate.tenant_id == tenant_id)
    )
    candidate = result.scalar_one_or_none()

    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    previous_status = candidate.pipeline_status

    if previous_status == body.new_status:
        raise HTTPException(status_code=400, detail="Candidate already in this status")

    candidate.pipeline_status = body.new_status

    await log_action(
        db,
        tenant_id=tenant_id,
        user_id=current_user.id,
        action="pipeline_move",
        entity_type="candidate",
        entity_id=str(candidate.id),
        details={
            "from_status": previous_status,
            "to_status": body.new_status,
        },
    )

    await db.commit()

    logger.info(
        "pipeline_move",
        candidate_id=str(candidate.id),
        from_status=previous_status,
        to_status=body.new_status,
        user_id=str(current_user.id),
    )

    return PipelineMoveResponse(
        id=str(candidate.id),
        pipeline_status=body.new_status,
        previous_status=previous_status,
    )
