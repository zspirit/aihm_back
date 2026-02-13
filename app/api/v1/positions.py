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
    normalize_skills,
)
from app.services.audit import log_action
from app.services.position_import import extract_position_from_text
from app.services.position_templates import POSITION_TEMPLATES

router = APIRouter(prefix="/positions", tags=["positions"])
limiter = Limiter(key_func=get_remote_address)


def _build_position_response(position, candidate_count: int = 0) -> PositionResponse:
    """Build a PositionResponse with normalized skills (backward compatible)."""
    return PositionResponse(
        id=str(position.id),
        title=position.title,
        description=position.description,
        required_skills=normalize_skills(position.required_skills or []),
        seniority_level=position.seniority_level,
        custom_questions=position.custom_questions,
        status=position.status,
        deadline=position.deadline,
        auto_advance_threshold=position.auto_advance_threshold,
        auto_reject_threshold=position.auto_reject_threshold,
        created_by=str(position.created_by),
        created_at=position.created_at,
        candidate_count=candidate_count,
    )


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
        responses.append(_build_position_response(pos, candidate_count=count))

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
        auto_advance_threshold=data.auto_advance_threshold,
        auto_reject_threshold=data.auto_reject_threshold,
        created_by=current_user.id,
    )
    db.add(position)
    await db.flush()

    try:
        await log_action(
            db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            action="create_position",
            entity_type="position",
            entity_id=str(position.id),
            details={"title": data.title},
        )
    except Exception:
        pass

    return _build_position_response(position, candidate_count=0)


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

    return _build_position_response(new_position, candidate_count=0)


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

    return _build_position_response(position, candidate_count=count)


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

    try:
        await log_action(
            db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            action="update_position",
            entity_type="position",
            entity_id=str(position.id),
            details={"updated_fields": list(update_data.keys())},
        )
    except Exception:
        pass

    count_result = await db.execute(
        select(func.count()).where(Candidate.position_id == position.id)
    )
    count = count_result.scalar()

    return _build_position_response(position, candidate_count=count)


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

    try:
        await log_action(
            db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            action="delete_position",
            entity_type="position",
            entity_id=str(position.id),
            details={"title": position.title},
        )
    except Exception:
        pass

    await db.delete(position)


@router.post("/{position_id}/optimize")
@limiter.limit("3/minute")
async def optimize_position(
    position_id: UUID,
    request: Request,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Analyze a job description with AI and suggest improvements."""
    import json

    from anthropic import Anthropic

    from app.core.config import get_settings
    from app.schemas.position import PositionOptimization

    settings = get_settings()

    result = await db.execute(
        select(Position).where(
            Position.id == position_id,
            Position.tenant_id == current_user.tenant_id,
        )
    )
    position = result.scalar_one_or_none()
    if not position:
        raise HTTPException(status_code=404, detail="Poste introuvable")

    skills_text = ""
    if position.required_skills:
        skill_names = []
        for s in position.required_skills:
            if isinstance(s, dict):
                skill_names.append(s.get("name", str(s)))
            else:
                skill_names.append(str(s))
        skills_text = ", ".join(skill_names)

    questions_text = ""
    if position.custom_questions:
        questions_text = "\n".join(f"- {q}" for q in position.custom_questions)

    prompt = f"""Analyse cette offre d'emploi et suggere des ameliorations. Reponds UNIQUEMENT en JSON valide.

POSTE:
- Titre: {position.title}
- Niveau: {position.seniority_level or "non specifie"}
- Description: {position.description or "Aucune description"}
- Competences requises: {skills_text or "Aucune competence listee"}
- Questions d'entretien existantes:
{questions_text or "Aucune question definie"}

Analyse selon ces 5 axes:

1. CLARTE: La description est-elle claire et specifique ? Suggere des reformulations pour les parties vagues.
2. COMPETENCES MANQUANTES: En fonction du titre et de la description, y a-t-il des competences qui devraient etre listees ?
3. INCLUSIVITE: Signale tout langage potentiellement discriminatoire ou genre. Suggere des alternatives neutres.
4. COMPETITIVITE: Note l'attractivite de l'offre (1-10) et suggere des ameliorations pour attirer plus de candidats.
5. QUESTIONS: Suggere 2-3 questions d'entretien personnalisees si peu ou pas de questions existent.

Format JSON attendu:
{{
    "clarity_score": 7,
    "clarity_suggestions": ["suggestion 1", "suggestion 2"],
    "missing_skills": [
        {{"name": "competence", "category": "technique", "level_required": 3, "reason": "raison"}}
    ],
    "inclusivity_score": 8,
    "inclusivity_flags": ["probleme detecte 1"],
    "competitiveness_score": 6,
    "competitiveness_suggestions": ["suggestion 1"],
    "suggested_questions": ["question 1", "question 2"],
    "improved_description": "description reecrite et amelioree du poste"
}}

REGLES:
- Tous les scores sont entre 1 et 10
- Les suggestions doivent etre concretes et actionnables
- La description amelioree doit etre professionnelle et inclusive
- Les competences manquantes doivent avoir category parmi: technique, experience, soft_skills, langue
- level_required entre 1 et 5
- Reponds en francais"""

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        text_content = response.content[0].text
        if "```json" in text_content:
            text_content = text_content.split("```json")[1].split("```")[0]
        elif "```" in text_content:
            text_content = text_content.split("```")[1].split("```")[0]

        data = json.loads(text_content.strip())

        optimization = PositionOptimization(
            clarity_score=max(1, min(10, data.get("clarity_score", 5))),
            clarity_suggestions=data.get("clarity_suggestions", []),
            missing_skills=data.get("missing_skills", []),
            inclusivity_score=max(1, min(10, data.get("inclusivity_score", 5))),
            inclusivity_flags=data.get("inclusivity_flags", []),
            competitiveness_score=max(1, min(10, data.get("competitiveness_score", 5))),
            competitiveness_suggestions=data.get("competitiveness_suggestions", []),
            suggested_questions=data.get("suggested_questions", []),
            improved_description=data.get("improved_description", position.description or ""),
        )

        return optimization
    except (json.JSONDecodeError, IndexError, KeyError):
        raise HTTPException(
            status_code=502,
            detail="Erreur lors de l'analyse IA de l'offre d'emploi",
        )
