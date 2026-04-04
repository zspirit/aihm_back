from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import delete as sql_delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_tenant_id, require_role
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.match_score import MatchScore, MatchSession
from app.models.position import Position
from app.models.user import User
from app.schemas.batch_matching import MatchCandidatesRequest, MatchSessionResponse
from app.schemas.position import (
    PaginatedPositions,
    PositionCreate,
    PositionDuplicateRequest,
    PositionImportTextRequest,
    PositionResponse,
    PositionUpdate,
    normalize_skills,
)
import structlog

from app.services.audit import log_action
from app.services.position_import import extract_position_from_text
from app.services.position_templates import POSITION_TEMPLATES

logger = structlog.get_logger()

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
    page_size: int = Query(20, ge=1, le=500),
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
        # Count candidates linked via Application table OR direct position_id
        count_result = await db.execute(
            select(func.count(func.distinct(Candidate.id)))
            .select_from(Candidate)
            .outerjoin(Application, Application.candidate_id == Candidate.id)
            .where(
                or_(
                    Candidate.position_id == pos.id,
                    Application.position_id == pos.id,
                )
            )
        )
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
    except Exception as e:
        logger.warning("audit_log_failed", action="create_position", error=str(e))

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
        select(func.count(func.distinct(Candidate.id)))
        .select_from(Candidate)
        .outerjoin(Application, Application.candidate_id == Candidate.id)
        .where(
            or_(
                Candidate.position_id == position.id,
                Application.position_id == position.id,
            )
        )
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
    except Exception as e:
        logger.warning("audit_log_failed", action="update_position", error=str(e))

    count_result = await db.execute(
        select(func.count(func.distinct(Candidate.id)))
        .select_from(Candidate)
        .outerjoin(Application, Application.candidate_id == Candidate.id)
        .where(
            or_(
                Candidate.position_id == position.id,
                Application.position_id == position.id,
            )
        )
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
    except Exception as e:
        logger.warning("audit_log_failed", action="delete_position", error=str(e))

    await db.delete(position)
    await db.commit()


@router.post("/bulk-delete", status_code=status.HTTP_200_OK)
async def bulk_delete_positions(
    body: dict,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """Delete multiple positions by IDs."""
    ids = body.get("ids", [])
    if not ids:
        raise HTTPException(status_code=400, detail="Aucun ID fourni")
    if len(ids) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 postes")
    uuids = [UUID(i) for i in ids]
    result = await db.execute(
        select(Position).where(Position.id.in_(uuids), Position.tenant_id == current_user.tenant_id)
    )
    positions_list = result.scalars().all()
    for pos in positions_list:
        await db.delete(pos)
    await db.commit()
    return {"deleted": len(positions_list)}


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

    import asyncio

    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    response = await asyncio.to_thread(
        client.messages.create,
        model=settings.ANTHROPIC_MODEL,
        max_tokens=2000,
        timeout=60.0,
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


@router.post(
    "/{position_id}/match-candidates",
    response_model=MatchSessionResponse,
    status_code=202,
)
async def match_candidates_for_position(
    position_id: UUID,
    body: MatchCandidatesRequest,
    current_user: User = Depends(require_role("admin", "recruiter")),
    db: AsyncSession = Depends(get_db),
):
    """
    Lancer un matching bidirectionnel depuis une fiche poste.
    Si candidate_ids est null, prend tous les candidats du tenant avec CV parsé.
    Retourne un session_id pour tracker la progression via SSE (/matching/sessions/{id}/events).
    """
    tenant_id = current_user.tenant_id

    # Vérifier que le poste appartient au tenant
    result = await db.execute(
        select(Position).where(
            Position.id == position_id,
            Position.tenant_id == tenant_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Poste introuvable")

    # Résoudre les candidats
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
            detail="Aucun candidat avec CV analysé trouvé",
        )

    total_pairs = len(candidate_uuids)

    # Calculer les paires manquantes si pas force_recompute
    pairs_to_compute = total_pairs
    if not body.force_recompute:
        result = await db.execute(
            select(MatchScore.candidate_id).where(
                MatchScore.tenant_id == tenant_id,
                MatchScore.position_id == position_id,
                MatchScore.candidate_id.in_(candidate_uuids),
            )
        )
        cached_cands = {row[0] for row in result.all()}
        pairs_to_compute = len(set(candidate_uuids) - cached_cands)

    # Créer la session de matching
    session = MatchSession(
        tenant_id=tenant_id,
        user_id=current_user.id,
        position_ids=[str(position_id)],
        candidate_ids=[str(cid) for cid in candidate_uuids],
        status="pending",
        total_pairs=total_pairs,
        computed_pairs=0,
    )
    db.add(session)
    await db.flush()
    session_id = str(session.id)
    await db.commit()

    logger.info(
        "match_session_created_for_position",
        session_id=session_id,
        position_id=str(position_id),
        candidates=len(candidate_uuids),
        pairs_to_compute=pairs_to_compute,
    )

    # Lancer le worker Celery, fallback inline si indisponible
    celery_available = False
    try:
        from app.workers.matching import compute_match_matrix
        compute_match_matrix.delay(session_id)
        celery_available = True
    except Exception:
        pass

    if not celery_available:
        import asyncio as _asyncio
        from starlette.concurrency import run_in_threadpool as _run_in_threadpool
        from app.core.database import async_session as _async_session
        from sqlalchemy import select as _select

        _sid = session_id

        async def _process_matching_inline():
            try:
                from app.services.batch_matching import compute_batch_matching
                await _run_in_threadpool(compute_batch_matching, _sid)
            except Exception as _exc:
                import structlog as _structlog
                _structlog.get_logger().error("inline_matching_error", session_id=_sid, error=str(_exc))
                async with _async_session() as _sess:
                    from app.models.match_score import MatchSession as _MatchSession
                    _r = await _sess.execute(_select(_MatchSession).where(_MatchSession.id == UUID(_sid)))
                    _ms = _r.scalar_one_or_none()
                    if _ms:
                        _ms.status = "failed"
                        await _sess.commit()

        _asyncio.create_task(_process_matching_inline())

    return MatchSessionResponse(
        session_id=session_id,
        total_pairs=total_pairs,
        status="pending",
    )
