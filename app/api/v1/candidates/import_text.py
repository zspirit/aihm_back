"""Endpoint candidate import-text — Phase 3.2 V1_ROADMAP.

Parse un blob de texte (LinkedIn copie, CV texte, profil libre) via Claude
et cree un candidate. Reutilise le pattern existant `/positions/import-text`.
"""
import json
import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.rate_limit import limiter
from app.models.candidate import Candidate
from app.models.user import User

router = APIRouter(tags=["candidates"])


class ImportTextPayload(BaseModel):
    text: str = Field(..., min_length=20, max_length=50000)
    position_id: Optional[uuid.UUID] = None


@router.post("/candidates/import-text")
@limiter.limit("5/minute")
async def import_candidate_from_text(
    request: Request,
    payload: ImportTextPayload = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Parse un texte (LinkedIn / CV) en candidate via Claude.

    En v0.0.1 : extraction naive (premier nom apres "Nom :", "Email :", etc.).
    Quand le service Claude est cable, on bascule sur l'analyse riche.
    """
    text = payload.text

    # Naive extraction — fallback sur quelques regex simples
    import re
    name_match = re.search(r"(?:nom|name)\s*[:\-]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", text, re.IGNORECASE)
    email_match = re.search(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b", text)
    phone_match = re.search(r"(?:\+\d{1,3}\s?)?(?:\(\d{1,4}\)\s?)?[\d\s\-]{8,}", text)

    name = name_match.group(1) if name_match else "Candidat importe"
    email = email_match.group(0) if email_match else None
    phone = phone_match.group(0).strip() if phone_match else None

    # Appel Claude pour extraction riche. En cas d'échec, fallback explicite
    # sur l'extraction naive (regex) et on flag dans parsed_data.
    parsed_data: dict = {
        "raw_text": text[:5000],
        "imported_via": "import-text",
        "ai_parser_used": False,
    }
    try:
        from app.services.copilot import call_claude_json
        prompt = f"""Tu es un parseur CV. Extrais du texte ci-dessous un objet JSON STRICT
avec les cles : name, email, phone, headline (1 ligne), summary (3-5 lignes),
skills (liste de strings), experiences (liste {{title, company, years}}),
education (liste {{degree, school, year}}). Si une info manque, mets null ou [].

TEXTE:
{text[:8000]}
"""
        result = call_claude_json(prompt, max_tokens=2000)
        if isinstance(result, dict):
            name = result.get("name") or name
            email = result.get("email") or email
            phone = result.get("phone") or phone
            parsed_data.update(result)
            parsed_data["ai_parser_used"] = True
            parsed_data["ai_model"] = "claude-sonnet-4-5"
    except Exception as exc:
        # On garde l'extraction naive mais on logue pour debug + on flag
        # le parsed_data pour que l'UI puisse signaler "parser dégradé".
        import logging
        logging.getLogger(__name__).warning(
            "import_text.claude_parse_failed",
            exc_info=exc,
            extra={"text_length": len(text)},
        )
        parsed_data["ai_parser_error"] = str(exc)[:200]

    if not email and not phone:
        raise HTTPException(
            status_code=400,
            detail="Email ou telephone introuvable dans le texte. Verifie le format.",
        )

    cand = Candidate(
        id=uuid.uuid4(),
        tenant_id=current_user.tenant_id,
        position_id=payload.position_id,
        name=name,
        email=email,
        phone=phone,
        pipeline_status="new",
        cv_parsed_data=parsed_data,
    )
    db.add(cand)
    await db.commit()
    await db.refresh(cand)

    return {
        "id": str(cand.id),
        "name": cand.name,
        "email": cand.email,
        "phone": cand.phone,
    }
