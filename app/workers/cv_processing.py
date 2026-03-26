import json

import structlog
from celery import shared_task

logger = structlog.get_logger()


def get_sync_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.core.config import get_settings

    settings = get_settings()
    sync_url = settings.DATABASE_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url)
    return Session(engine)


@shared_task(name="cv.process", bind=True, max_retries=3)
def process_cv(self, candidate_id: str, position_id: str | None = None, bulk_import_id: str | None = None):
    logger.info("cv_processing_start", candidate_id=candidate_id, position_id=position_id, bulk_import_id=bulk_import_id)

    session = get_sync_session()
    success = False
    try:
        from uuid import UUID

        from app.models.candidate import Candidate
        from app.models.position import Position

        candidate = session.get(Candidate, UUID(candidate_id))
        if not candidate or not candidate.cv_file_path:
            logger.warning("cv_processing_skip", candidate_id=candidate_id, reason="no_cv")
            success = True  # Not an error, just nothing to do
            return

        # Use explicit position_id if provided, else fall back to candidate.position_id
        effective_position_id = UUID(position_id) if position_id else candidate.position_id
        position = session.get(Position, effective_position_id) if effective_position_id else None
        if candidate.position_id and not position:
            logger.warning("position_not_found", position_id=str(candidate.position_id))

        # Parse CV
        parsed_data = parse_cv_file(candidate.cv_file_path)
        candidate.cv_parsed_data = {**(candidate.cv_parsed_data or {}), **parsed_data}

        # Load tenant scoring weights
        from app.models.tenant import Tenant
        tenant = session.get(Tenant, candidate.tenant_id)
        scoring_weights = {
            "skills": tenant.scoring_skills_weight if tenant else 50,
            "experience": tenant.scoring_experience_weight if tenant else 30,
            "education": tenant.scoring_education_weight if tenant else 20,
        }

        # Score CV
        auto_advanced = False
        if position:
            # Score against specific position
            score_result = score_cv(parsed_data, position, weights=scoring_weights)
            candidate.cv_score = score_result["score"]
            candidate.cv_score_explanation = score_result["explanation"]
            cv_score = score_result["score"]

            # Workflow automation
            if position.auto_reject_threshold is not None and cv_score < position.auto_reject_threshold:
                candidate.pipeline_status = "rejected"
                logger.info("auto_rejected", candidate_id=candidate_id, score=cv_score, threshold=position.auto_reject_threshold)
            elif position.auto_advance_threshold is not None and cv_score >= position.auto_advance_threshold:
                candidate.pipeline_status = "invited"
                auto_advanced = True
                logger.info("auto_advanced", candidate_id=candidate_id, score=cv_score, threshold=position.auto_advance_threshold)
            else:
                candidate.pipeline_status = "cv_analyzed"
        else:
            # Vivier: score CV quality (no position comparison)
            quality_result = score_cv_quality(parsed_data)
            candidate.cv_score = quality_result["score"]
            candidate.cv_score_explanation = quality_result["explanation"]
            candidate.pipeline_status = "cv_analyzed"
            logger.info("cv_quality_scored", candidate_id=candidate_id, score=quality_result["score"])

        session.commit()
        success = True
        logger.info(
            "cv_processing_done",
            candidate_id=candidate_id,
            score=candidate.cv_score,
        )

        # Trigger question generation + consent email (only if position exists)
        if position:
            try:
                from app.workers.notifications import send_consent_email
                from app.workers.question_generation import generate_questions

                generate_questions.delay(candidate_id)

                if auto_advanced:
                    send_consent_email.delay(candidate_id)
                elif position.auto_reject_threshold is None and position.auto_advance_threshold is None:
                    send_consent_email.delay(candidate_id)
            except Exception:
                logger.warning("celery_downstream_unavailable", candidate_id=candidate_id)

    except Exception as e:
        session.rollback()
        logger.error("cv_processing_error", candidate_id=candidate_id, error=str(e))
        try:
            raise self.retry(exc=e, countdown=30)
        except Exception:
            pass  # If not in Celery context (inline), just log
    finally:
        # Update BulkImport progress atomically (if part of a bulk import)
        if bulk_import_id:
            _update_bulk_import_progress(session, bulk_import_id, success)
        session.close()


def _update_bulk_import_progress(session, bulk_import_id: str, success: bool):
    """Atomically update BulkImport counters after one CV is processed."""
    from datetime import datetime, timezone
    from uuid import UUID

    from sqlalchemy import text as sql_text

    try:
        bid = UUID(bulk_import_id)
        if success:
            session.execute(sql_text(
                "UPDATE bulk_imports SET processed_count = processed_count + 1, "
                "success_count = success_count + 1 WHERE id = :bid"
            ), {"bid": str(bid)})
        else:
            session.execute(sql_text(
                "UPDATE bulk_imports SET processed_count = processed_count + 1, "
                "error_count = error_count + 1 WHERE id = :bid"
            ), {"bid": str(bid)})
        session.commit()

        # Check if all done — mark completed
        from app.models.bulk_import import BulkImport
        bi = session.get(BulkImport, bid)
        if bi and bi.processed_count >= bi.total_count:
            bi.status = "completed"
            bi.completed_at = datetime.now(timezone.utc)
            session.commit()
            logger.info("bulk_import_completed", import_id=bulk_import_id,
                        total=bi.total_count, success=bi.success_count, errors=bi.error_count)
    except Exception as exc:
        logger.warning("bulk_import_progress_error", import_id=bulk_import_id, error=str(exc))
        try:
            session.rollback()
        except Exception:
            pass


def parse_cv_file(file_path: str) -> dict:
    from app.services.storage import download_file

    parts = file_path.split("/", 1)
    content = download_file(parts[0], parts[1])

    ext = file_path.rsplit(".", 1)[-1].lower()
    if ext == "pdf":
        return parse_pdf(content)
    elif ext in ("docx", "doc"):
        return parse_docx(content)
    else:
        return {"raw_text": content.decode("utf-8", errors="ignore")}


def parse_pdf(content: bytes) -> dict:
    import fitz

    doc = fitz.open(stream=content, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    return extract_structured_data(text)


def parse_docx(content: bytes) -> dict:
    from io import BytesIO

    from docx import Document

    doc = Document(BytesIO(content))
    text = "\n".join([para.text for para in doc.paragraphs])
    return extract_structured_data(text)


def extract_structured_data(text: str) -> dict:
    from anthropic import Anthropic

    from app.core.config import get_settings

    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=1500,
        timeout=60.0,
        messages=[
            {
                "role": "user",
                "content": f"""Extrais les informations structurees de ce CV. Reponds UNIQUEMENT en JSON valide.

CV:
{text[:4000]}

Format JSON attendu:
{{
    "name": "nom complet",
    "email": "email",
    "phone": "telephone",
    "skills": ["competence1", "competence2"],
    "experience_years": 0,
    "experiences": [
        {{"title": "poste", "company": "entreprise", "duration": "duree", "description": "resume"}}
    ],
    "education": [
        {{"degree": "diplome", "school": "ecole", "year": "annee"}}
    ],
    "languages": ["francais", "anglais"],
    "summary": "resume en 2-3 phrases"
}}""",
            }
        ],
    )

    try:
        text_content = response.content[0].text
        # Extract JSON from response
        if "```json" in text_content:
            text_content = text_content.split("```json")[1].split("```")[0]
        elif "```" in text_content:
            text_content = text_content.split("```")[1].split("```")[0]
        return json.loads(text_content.strip())
    except (json.JSONDecodeError, IndexError):
        return {"raw_text": text[:2000], "parse_error": True}


def score_cv(parsed_data: dict, position, weights: dict | None = None) -> dict:
    from anthropic import Anthropic

    from app.core.config import get_settings

    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    sw = (weights or {}).get("skills", 50)
    ew = (weights or {}).get("experience", 30)
    edw = (weights or {}).get("education", 20)

    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=2000,
        timeout=60.0,
        messages=[
            {
                "role": "user",
                "content": f"""Evalue ce CV par rapport a cette fiche de poste. Reponds UNIQUEMENT en JSON.

FICHE DE POSTE:
- Titre: {position.title}
- Description: {position.description[:1000]}
- Competences requises: {json.dumps(position.required_skills, ensure_ascii=False)}
- Niveau: {position.seniority_level}

CV PARSE:
{json.dumps(parsed_data, ensure_ascii=False)[:2000]}

PONDERATION DES CRITERES:
- skills_match : {sw}% du score global (competences techniques et fonctionnelles)
- experience_match : {ew}% du score global (annees + pertinence du parcours)
- education_match : {edw}% du score global (diplomes, certifications)
Le score global = (skills_match * 0.5) + (experience_match * 0.3) + (education_match * 0.2)

GUIDE D'INTERPRETATION DES SCORES:
- Score 80+ : excellent match, competences demontrees en projet sur la majorite des requis
- Score 60-79 : bon match, competences presentes avec quelques lacunes
- Score 40-59 : match partiel, lacunes significatives sur des competences cles
- Score <40 : faible correspondance avec le poste

METHODE D'EVALUATION DES COMPETENCES (CRITIQUE):
1. Une competence est "matched" UNIQUEMENT si elle est DEMONTREE dans un projet ou une experience concrete (pas juste listee dans les skills)
2. Une competence simplement listee avec "knowledge", "basics", "notions" ou sans projet associe = NON VALIDEE comme matched
3. Distinguer clairement : utiliser une techno en tant que consommateur (ex: appeler une API) vs la maitriser (ex: concevoir et developper des APIs)
4. Pour un poste Full Stack : verifier que le candidat a une experience REELLE sur les DEUX parties (frontend ET backend). Un profil 90% frontend avec des mots-cles backend ne doit PAS etre score comme full stack
5. Le keyword stuffing (lister beaucoup de technos sans experience concrete) doit REDUIRE la confiance dans les competences declarees, pas l'augmenter
6. Competences transferables : accepter les equivalences technologiques SEULEMENT si demontrees en projet (ex: PHP/Laravel backend = transferable vers Python backend, mais "Node.js knowledge" sans projet ≠ competence backend)

REGLES STRICTES:
- Score de 0 a 100, base sur des competences DEMONTREES en projet uniquement
- PAS d'inference de personnalite ou de motivation
- PAS de recommandation d'embauche
- Justifie chaque sous-score par des elements factuels du CV (nommer les projets concrets)
- Sois sceptique envers les longues listes de skills sans projets correspondants

Format JSON:
{{
    "score": 75,
    "explanation": {{
        "skills_match": {{"score": 80, "matched": ["skill1"], "missing": ["skill2"], "transferable": ["skill3"], "justification": "..."}},
        "experience_match": {{"score": 70, "justification": "..."}},
        "education_match": {{"score": 75, "justification": "..."}}
    }}
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
        return json.loads(text_content.strip())
    except (json.JSONDecodeError, IndexError) as e:
        raw = response.content[0].text if response.content else "empty"
        logger.error("cv_scoring_json_error", error=str(e), raw_response=raw[:500], stop_reason=response.stop_reason)
        return {"score": 0, "explanation": {"error": f"Scoring failed: {e}"}}


def score_cv_quality(parsed_data: dict) -> dict:
    """Score intrinsic CV quality (without comparing to a specific position)."""
    from anthropic import Anthropic

    from app.core.config import get_settings

    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=settings.ANTHROPIC_MODEL,
        max_tokens=1500,
        timeout=60.0,
        messages=[
            {
                "role": "user",
                "content": f"""Evalue la qualite intrinseque de ce CV (sans comparaison a un poste specifique).
Reponds UNIQUEMENT en JSON valide.

CV PARSE:
{json.dumps(parsed_data, ensure_ascii=False)[:3000]}

CRITERES D'EVALUATION (score de 0 a 100):
- technical_depth (30%) : profondeur technique — competences demontrees en projet concret, pas juste listees
- experience_quality (30%) : qualite du parcours — progression, entreprises, impact mesurable, duree
- education_relevance (20%) : formation — diplomes, certifications, pertinence
- cv_completeness (20%) : completude du CV — informations de contact, structure claire, description des experiences

GUIDE:
- 80+ : profil senior/expert, parcours solide avec preuves concretes
- 60-79 : bon profil, experiences pertinentes avec quelques lacunes
- 40-59 : profil junior ou CV incomplet
- <40 : CV tres lacunaire ou peu exploitable

REGLES:
- Score base sur des elements FACTUELS du CV uniquement
- PAS d'inference de personnalite ou motivation
- Penaliser le keyword stuffing (longues listes sans preuves)
- Valoriser les realisations concretes et mesurables

Format JSON:
{{
    "score": 65,
    "explanation": {{
        "technical_depth": {{"score": 70, "justification": "..."}},
        "experience_quality": {{"score": 60, "justification": "..."}},
        "education_relevance": {{"score": 65, "justification": "..."}},
        "cv_completeness": {{"score": 70, "justification": "..."}}
    }}
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
        return json.loads(text_content.strip())
    except (json.JSONDecodeError, IndexError) as e:
        raw = response.content[0].text if response.content else "empty"
        logger.error("cv_quality_json_error", error=str(e), raw_response=raw[:500])
        return {"score": 0, "explanation": {"error": f"Quality scoring failed: {e}"}}
