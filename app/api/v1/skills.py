"""Skills management and search endpoints (Phase 3)."""
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.dialects.postgresql import array_agg

from app.core.dependencies import get_db, get_current_user
from app.models import User, Skill, Candidate, Position, Application
from app.schemas.skill import SkillResponse, SkillSearchResponse, SkillTrendingResponse

router = APIRouter(prefix="/skills", tags=["skills"])


@router.post("/search", response_model=list[SkillSearchResponse])
async def search_skills(
    query: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Search for skills by name/description."""
    search_pattern = f"%{query.lower()}%"

    result = await db.execute(
        select(Skill)
        .where(
            and_(
                Skill.tenant_id == current_user.tenant_id,
                func.lower(Skill.name).like(search_pattern),
            )
        )
        .limit(limit)
    )

    return result.scalars().all()


@router.get("/similar/{skill_id}", response_model=list[SkillSearchResponse])
async def get_similar_skills(
    skill_id: UUID,
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get similar skills based on category."""
    skill = await db.get(Skill, skill_id)
    if not skill or skill.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="Skill not found")

    result = await db.execute(
        select(Skill)
        .where(
            and_(
                Skill.tenant_id == current_user.tenant_id,
                Skill.category == skill.category,
                Skill.id != skill_id,
            )
        )
        .limit(limit)
    )

    return result.scalars().all()


@router.get("/trending", response_model=list[SkillTrendingResponse])
async def get_trending_skills(
    limit: int = Query(20, ge=1, le=100),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get trending skills in recent positions."""
    from datetime import datetime, timezone, timedelta

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

    result = await db.execute(
        select(
            Skill.id,
            Skill.name,
            Skill.category,
            func.count(Application.id).label("mention_count"),
        )
        .select_from(Skill)
        .join(Application, Application.id == Skill.id, isouter=True)
        .where(
            and_(
                Skill.tenant_id == current_user.tenant_id,
                Application.created_at >= cutoff_date,
            )
        )
        .group_by(Skill.id, Skill.name, Skill.category)
        .order_by(func.count(Application.id).desc())
        .limit(limit)
    )

    rows = result.all()
    return [
        {
            "id": str(row[0]),
            "name": row[1],
            "category": row[2],
            "mention_count": row[3] or 0,
        }
        for row in rows
    ]
