"""Proactive sourcing endpoints — Phase 4.4 V1_ROADMAP.

Mines the existing candidate database to surface profiles that match an
open position, *without* requiring a fresh application. Use case: a
recruiter opens a new position; instead of waiting for inbound apps,
the system proposes 5–10 past candidates whose extracted CV skills
overlap with the position's required_skills.

Endpoints:
- GET /positions/{id}/sourcing-candidates  → ranked list of (candidate, overlap)
- GET /candidates/{id}/sourcing-positions  → ranked list of open positions
                                              (already exists in matching.py
                                              as candidate_position_matches —
                                              not duplicated here)

Scoring is intentionally simple (skill-overlap ratio) so the result is
explainable. The deeper LLM-scored matching lives in batch_matching.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.candidate import Candidate
from app.models.position import Position
from app.models.user import User

router = APIRouter(tags=["sourcing"])


class SourcingHit(BaseModel):
    candidate_id: UUID
    name: str
    email: Optional[str]
    overlap_score: int  # 0-100, share of required skills covered
    matched_skills: list[str]
    cv_score: Optional[float] = None
    pipeline_status: str


class SourcingResponse(BaseModel):
    position_id: UUID
    required_skills_count: int
    candidates_pool_size: int
    suggestions: list[SourcingHit]


def _normalize_skill(s: str) -> str:
    return s.strip().lower()


def _candidate_skills(candidate: Candidate) -> list[str]:
    cv = candidate.cv_parsed_data or {}
    raw = cv.get("skills") or []
    out = []
    for s in raw:
        if isinstance(s, str):
            out.append(_normalize_skill(s))
        elif isinstance(s, dict) and s.get("name"):
            out.append(_normalize_skill(s["name"]))
    return out


def _required_skill_names(pos: Position) -> list[str]:
    out = []
    for s in pos.required_skills or []:
        if isinstance(s, str):
            out.append(_normalize_skill(s))
        elif isinstance(s, dict) and s.get("name"):
            out.append(_normalize_skill(s["name"]))
    return out


@router.get(
    "/positions/{position_id}/sourcing-candidates",
    response_model=SourcingResponse,
)
async def sourcing_candidates(
    position_id: UUID,
    min_overlap: int = Query(30, ge=0, le=100),
    limit: int = Query(10, ge=1, le=100),
    exclude_already_applied: bool = Query(
        True,
        description="Skip candidates whose Candidate.position_id already matches this position.",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Find past candidates whose extracted CV skills overlap with this
    position's required_skills.
    """
    pos_res = await db.execute(
        select(Position).where(
            Position.id == position_id,
            Position.tenant_id == current_user.tenant_id,
        )
    )
    pos = pos_res.scalar_one_or_none()
    if pos is None:
        raise HTTPException(status_code=404, detail="position not found")

    required = _required_skill_names(pos)
    if not required:
        return SourcingResponse(
            position_id=position_id,
            required_skills_count=0,
            candidates_pool_size=0,
            suggestions=[],
        )

    # Scan only candidates with parsed CV data — anything without is unscorable.
    stmt = (
        select(Candidate)
        .where(
            Candidate.tenant_id == current_user.tenant_id,
            Candidate.cv_parsed_data.isnot(None),
        )
        .order_by(desc(Candidate.created_at))
    )
    if exclude_already_applied:
        # Filter "already applied to this exact position".
        stmt = stmt.where(
            (Candidate.position_id != position_id) | (Candidate.position_id.is_(None))
        )
    candidates = (await db.execute(stmt)).scalars().all()

    hits: list[SourcingHit] = []
    for cand in candidates:
        cand_skills = _candidate_skills(cand)
        if not cand_skills:
            continue
        matched = []
        for req in required:
            for cs in cand_skills:
                if req == cs or req in cs or cs in req:
                    matched.append(req)
                    break
        if not matched:
            continue
        overlap = round(len(matched) / len(required) * 100)
        if overlap < min_overlap:
            continue
        hits.append(SourcingHit(
            candidate_id=cand.id,
            name=cand.name,
            email=cand.email,
            overlap_score=overlap,
            matched_skills=matched,
            cv_score=cand.cv_score,
            pipeline_status=cand.pipeline_status,
        ))

    # Best overlap first; tie-break by CV score (higher first), then most recent.
    hits.sort(
        key=lambda h: (h.overlap_score, h.cv_score or 0),
        reverse=True,
    )

    return SourcingResponse(
        position_id=position_id,
        required_skills_count=len(required),
        candidates_pool_size=len(candidates),
        suggestions=hits[:limit],
    )
