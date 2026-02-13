from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_tenant_id, require_role
from app.models.candidate import Candidate
from app.models.position import Position
from app.models.user import User
from app.schemas.position import (
    PaginatedPositions,
    PositionCreate,
    PositionDuplicateRequest,
    PositionImportTextRequest,
    PositionResponse,
    PositionUpdate,
)
from app.services.position_import import extract_position_from_text
from app.services.position_templates import POSITION_TEMPLATES

router = APIRouter(prefix="/positions", tags=["positions"])
limiter = Limiter(key_func=get_remote_address)


@router.get("", response_model=PaginatedPositions)
async def list_positions(
    status_filter: str | None = None,
    search: str | None = Query(None, description="Search in title and description"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    query = select(Position).where(Position.tenant_id == tenant_id)
    count_query = select(func.count()).select_from(Position).where(Position.tenant_id == tenant_id)

    if status_filter:
        query = query.where(Position.status == status_filter)
        count_query = count_query.where(Position.status == status_filter)

    if search:
        search_filter = or_(
            Position.title.ilike(f"%{search}%"),
            Position.description.ilike(f"%{search}%"),
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    total = (await db.execute(count_query)).scalar()

    query = query.order_by(Position.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    positions = result.scalars().all()

    responses = []
    for pos in positions:
        count_result = await db.execute(select(func.count()).where(Candidate.position_id == pos.id))
        count = count_result.scalar()
        resp = PositionResponse(
            id=str(pos.id),
            title=pos.title,
            description=pos.description,
            required_skills=pos.required_skills,
            seniority_level=pos.seniority_level,
            custom_questions=pos.custom_questions,
            status=pos.status,
            deadline=pos.deadline,
            created_by=str(pos.created_by),
            created_at=pos.created_at,
            candidate_count=count,
        )
        responses.append(resp)

    return PaginatedPositions(
        items=responses,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=PositionResponse, status_code=status.HTTP_201_CREATED)
async def create_position(
    data: PositionCreate,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    position = Position(
        tenant_id=current_user.tenant_id,
        title=data.title,
        description=data.description,
        required_skills=data.required_skills,
        seniority_level=data.seniority_level,
        custom_questions=data.custom_questions,
        deadline=data.deadline,
        created_by=current_user.id,
    )
    db.add(position)
    await db.flush()

    return PositionResponse(
        id=str(position.id),
        title=position.title,
        description=position.description,
        required_skills=position.required_skills,
        seniority_level=position.seniority_level,
        custom_questions=position.custom_questions,
        status=position.status,
        deadline=position.deadline,
        created_by=str(position.created_by),
        created_at=position.created_at,
        candidate_count=0,
    )


@router.get("/templates")
async def list_templates(current_user: User = Depends(get_current_user)):
    """
    List available position templates.
    """
    return POSITION_TEMPLATES


@router.post("/import-text")
@limiter.limit("5/minute")
async def import_text(
    request: Request,
    body: PositionImportTextRequest,
    current_user: User = Depends(require_role("admin", "recruiter")),
):
    """
    Import position from raw text using AI extraction.
    Rate limited to 5 requests per minute.
    """
    result = extract_position_from_text(body.text)
    return result


@router.post("/{position_id}/duplicate", status_code=status.HTTP_201_CREATED, response_model=PositionResponse)
async def duplicate_position(
    position_id: UUID,
    body: PositionDuplicateRequest | None = None,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """
    Duplicate an existing position.
    """
    # Load source position
    result = await db.execute(
        select(Position).where(
            Position.id == position_id,
            Position.tenant_id == current_user.tenant_id,
        )
    )
    source_position = result.scalar_one_or_none()
    if not source_position:
        raise HTTPException(status_code=404, detail="Poste introuvable")

    # Create duplicate
    new_title = body.title if body and body.title else f"Copie de - {source_position.title}"

    new_position = Position(
        tenant_id=current_user.tenant_id,
        title=new_title,
        description=source_position.description,
        required_skills=source_position.required_skills,
        seniority_level=source_position.seniority_level,
        custom_questions=source_position.custom_questions,
        status="draft",
        deadline=source_position.deadline,
        created_by=current_user.id,
    )
    db.add(new_position)
    await db.flush()

    return PositionResponse(
        id=str(new_position.id),
        title=new_position.title,
        description=new_position.description,
        required_skills=new_position.required_skills,
        seniority_level=new_position.seniority_level,
        custom_questions=new_position.custom_questions,
        status=new_position.status,
        deadline=new_position.deadline,
        created_by=str(new_position.created_by),
        created_at=new_position.created_at,
        candidate_count=0,
    )


@router.get("/{position_id}", response_model=PositionResponse)
async def get_position(
    position_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Position).where(Position.id == position_id, Position.tenant_id == tenant_id)
    )
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status_code=404, detail="Poste introuvable")

    count_result = await db.execute(
        select(func.count()).where(Candidate.position_id == position.id)
    )
    count = count_result.scalar()

    return PositionResponse(
        id=str(position.id),
        title=position.title,
        description=position.description,
        required_skills=position.required_skills,
        seniority_level=position.seniority_level,
        custom_questions=position.custom_questions,
        status=position.status,
        deadline=position.deadline,
        created_by=str(position.created_by),
        created_at=position.created_at,
        candidate_count=count,
    )


@router.put("/{position_id}", response_model=PositionResponse)
async def update_position(
    position_id: UUID,
    data: PositionUpdate,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Position).where(
            Position.id == position_id,
            Position.tenant_id == current_user.tenant_id,
        )
    )
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status_code=404, detail="Poste introuvable")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(position, field, value)
    await db.flush()

    count_result = await db.execute(
        select(func.count()).where(Candidate.position_id == position.id)
    )
    count = count_result.scalar()

    return PositionResponse(
        id=str(position.id),
        title=position.title,
        description=position.description,
        required_skills=position.required_skills,
        seniority_level=position.seniority_level,
        custom_questions=position.custom_questions,
        status=position.status,
        deadline=position.deadline,
        created_by=str(position.created_by),
        created_at=position.created_at,
        candidate_count=count,
    )


@router.delete("/{position_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_position(
    position_id: UUID,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Position).where(
            Position.id == position_id,
            Position.tenant_id == current_user.tenant_id,
        )
    )
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status_code=404, detail="Poste introuvable")
    await db.delete(position)
