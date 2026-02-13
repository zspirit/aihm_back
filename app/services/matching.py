import json
from uuid import UUID

import structlog
from anthropic import Anthropic
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.candidate import Candidate
from app.models.position import Position

logger = structlog.get_logger()


async def pre_filter_candidates(
    db: AsyncSession,
    tenant_id: UUID,
    exclude_position_id: UUID | None = None,
    required_skills: list[str] | None = None,
    seniority_level: str | None = None,
    limit: int = 30,
) -> list[dict]:
    """
    Pre-filter candidates based on basic criteria.
    Returns candidates from other positions in the tenant.
    """
    query = (
        select(Candidate, Position)
        .join(Position, Candidate.position_id == Position.id)
        .where(Candidate.tenant_id == tenant_id)
    )

    # Exclude candidates already in target position
    if exclude_position_id:
        query = query.where(Candidate.position_id != exclude_position_id)

    # Only consider candidates with parsed CV data
    query = query.where(Candidate.cv_parsed_data.isnot(None))

    # Order by CV score
    query = query.order_by(Candidate.cv_score.desc().nulls_last())

    # Limit results
    query = query.limit(limit * 2)  # Fetch more for filtering

    result = await db.execute(query)
    rows = result.all()

    candidates = []
    for candidate, position in rows:
        # Build candidate dict
        candidate_dict = {
            "candidate_id": str(candidate.id),
            "name": candidate.name,
            "email": candidate.email,
            "source_position_id": str(position.id),
            "source_position_title": position.title,
            "cv_score": candidate.cv_score,
            "cv_parsed_data": candidate.cv_parsed_data or {},
        }

        # Apply skill filter if provided
        if required_skills:
            parsed_skills = candidate.cv_parsed_data.get("skills", []) if candidate.cv_parsed_data else []
            # Check if at least one skill matches (case-insensitive)
            parsed_skills_lower = [s.lower() for s in parsed_skills]
            required_skills_lower = [s.lower() for s in required_skills]
            has_match = any(skill in parsed_skills_lower for skill in required_skills_lower)
            if not has_match:
                continue

        candidates.append(candidate_dict)

        if len(candidates) >= limit:
            break

    logger.info(
        "pre_filter_candidates",
        tenant_id=str(tenant_id),
        total_found=len(candidates),
        requested_limit=limit,
    )

    return candidates


def ai_score_matches(
    candidates: list[dict],
    position_data: dict,
    limit: int = 20,
) -> list[dict]:
    """
    Use Claude to score candidates against position criteria.
    Sync function for Celery workers.
    """
    if not candidates:
        return []

    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    # Build prompt with all candidates
    candidates_text = ""
    for i, candidate in enumerate(candidates, 1):
        cv_data = candidate.get("cv_parsed_data", {})
        candidates_text += f"""
CANDIDAT {i}:
- ID: {candidate['candidate_id']}
- Nom: {candidate['name']}
- Poste actuel: {candidate['source_position_title']}
- Score CV actuel: {candidate.get('cv_score', 'N/A')}
- Competences: {json.dumps(cv_data.get('skills', []), ensure_ascii=False)}
- Experience: {cv_data.get('experience_years', 'N/A')} ans
- Resume: {cv_data.get('summary', 'N/A')}
---
"""

    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=2000,
        messages=[
            {
                "role": "user",
                "content": f"""Evalue ces candidats par rapport a ce nouveau poste. Reponds UNIQUEMENT en JSON valide.

NOUVEAU POSTE:
- Titre: {position_data.get('title', '')}
- Description: {position_data.get('description', '')[:1000]}
- Competences requises: {json.dumps(position_data.get('required_skills', []), ensure_ascii=False)}
- Niveau: {position_data.get('seniority_level', 'mid')}

CANDIDATS A EVALUER:
{candidates_text}

REGLES STRICTES:
- Evalue chaque candidat de 0 a 100 pour ce nouveau poste
- Base ton evaluation UNIQUEMENT sur des criteres observables (competences, experience)
- PAS d'inference de personnalite ou motivation
- PAS de recommandation d'embauche directe
- Justifie chaque score avec des elements factuels

Format JSON attendu:
{{
    "matches": [
        {{
            "candidate_id": "uuid",
            "match_score": 85,
            "match_reasons": {{
                "skills_overlap": {{"score": 90, "details": "8/10 competences matchent"}},
                "experience_relevance": {{"score": 80, "details": "5 ans d'experience pertinente"}},
                "seniority_fit": {{"score": 85, "details": "Niveau senior adapte au poste"}}
            }}
        }}
    ]
}}""",
            }
        ],
    )

    try:
        text_content = response.content[0].text
        if "```json" in text_content:
            text_content = text_content.split("```json")[1].split("```")[0]
        elif "```" in text_content:
            text_content = text_content.split("```")[1].split("```")[0]

        result = json.loads(text_content.strip())
        matches = result.get("matches", [])

        # Enrich matches with candidate data
        candidate_map = {c["candidate_id"]: c for c in candidates}
        enriched_matches = []
        for match in matches:
            candidate_id = match.get("candidate_id")
            if candidate_id in candidate_map:
                candidate = candidate_map[candidate_id]
                enriched_matches.append(
                    {
                        "candidate_id": candidate_id,
                        "name": candidate["name"],
                        "email": candidate.get("email"),
                        "source_position_id": candidate["source_position_id"],
                        "source_position_title": candidate["source_position_title"],
                        "cv_score": candidate.get("cv_score"),
                        "match_score": match.get("match_score", 0),
                        "match_reasons": match.get("match_reasons", {}),
                    }
                )

        # Sort by match_score DESC and limit
        enriched_matches.sort(key=lambda x: x["match_score"], reverse=True)
        enriched_matches = enriched_matches[:limit]

        logger.info("ai_score_matches_success", matches_count=len(enriched_matches))
        return enriched_matches

    except (json.JSONDecodeError, IndexError, KeyError) as e:
        logger.error("ai_score_matches_error", error=str(e))
        return []
