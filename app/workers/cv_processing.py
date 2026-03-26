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
def process_cv(self, candidate_id: str, position_id: str | None = None):
    logger.info("cv_processing_start", candidate_id=candidate_id, position_id=position_id)

    session = get_sync_session()
    try:
        from uuid import UUID

        from app.models.candidate import Candidate
        from app.models.position import Position

        candidate = session.get(Candidate, UUID(candidate_id))
        if not candidate or not candidate.cv_file_path:
            logger.warning("cv_processing_skip", candidate_id=candidate_id, reason="no_cv")
            return

        # Use explicit position_id if provided, else fall back to candidate.position_id
        effective_position_id = UUID(position_id) if position_id else candidate.position_id
        position = session.get(Position, effective_position_id) if effective_position_id else None
        if candidate.position_id and not position:
            logger.warning("position_not_found", position_id=str(candidate.position_id))

        # Parse CV
        parsed_data = parse_cv_file(candidate.cv_file_path)
        candidate.cv_parsed_data = {**(candidate.cv_parsed_data or {}), **parsed_data}

        # Score CV against position (skip scoring if no position = vivier)
        auto_advanced = False
        if position:
            score_result = score_cv(parsed_data, position)
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
            candidate.pipeline_status = "cv_analyzed"
            logger.info("cv_parsed_no_position", candidate_id=candidate_id)

        session.commit()
        logger.info(
            "cv_processing_done",
            candidate_id=candidate_id,
            score=score_result["score"],
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
        session.close()


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


def score_cv(parsed_data: dict, position) -> dict:
    from anthropic import Anthropic

    from app.core.config import get_settings

    settings = get_settings()
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

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
- skills_match : 50% du score global (competences techniques et fonctionnelles)
- experience_match : 30% du score global (annees + pertinence du parcours)
- education_match : 20% du score global (diplomes, certifications)
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
