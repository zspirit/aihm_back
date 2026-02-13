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
def process_cv(self, candidate_id: str):
    logger.info("cv_processing_start", candidate_id=candidate_id)

    session = get_sync_session()
    try:
        from uuid import UUID

        from app.models.candidate import Candidate
        from app.models.position import Position

        candidate = session.get(Candidate, UUID(candidate_id))
        if not candidate or not candidate.cv_file_path:
            logger.warning("cv_processing_skip", candidate_id=candidate_id, reason="no_cv")
            return

        position = session.get(Position, candidate.position_id)

        # Parse CV
        parsed_data = parse_cv_file(candidate.cv_file_path)
        candidate.cv_parsed_data = parsed_data

        # Score CV against position
        score_result = score_cv(parsed_data, position)
        candidate.cv_score = score_result["score"]
        candidate.cv_score_explanation = score_result["explanation"]
        candidate.pipeline_status = "cv_analyzed"

        cv_score = score_result["score"]

        # Workflow automation
        auto_advanced = False
        if position.auto_reject_threshold is not None and cv_score < position.auto_reject_threshold:
            candidate.pipeline_status = "rejected"
            logger.info("auto_rejected", candidate_id=candidate_id, score=cv_score, threshold=position.auto_reject_threshold)
        elif position.auto_advance_threshold is not None and cv_score >= position.auto_advance_threshold:
            candidate.pipeline_status = "invited"
            auto_advanced = True
            logger.info("auto_advanced", candidate_id=candidate_id, score=cv_score, threshold=position.auto_advance_threshold)

        session.commit()
        logger.info(
            "cv_processing_done",
            candidate_id=candidate_id,
            score=score_result["score"],
        )

        # Trigger question generation + consent email
        from app.workers.notifications import send_consent_email
        from app.workers.question_generation import generate_questions

        generate_questions.delay(candidate_id)

        if auto_advanced:
            # Workflow automation triggered consent email
            send_consent_email.delay(candidate_id)
        elif position.auto_reject_threshold is None and position.auto_advance_threshold is None:
            # No automation configured — send consent email as before
            send_consent_email.delay(candidate_id)

    except Exception as e:
        session.rollback()
        logger.error("cv_processing_error", candidate_id=candidate_id, error=str(e))
        raise self.retry(exc=e, countdown=30)
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
        max_tokens=1000,
        messages=[
            {
                "role": "user",
                "content": f"""Evalue ce CV par rapport a cette fiche de poste. Reponds UNIQUEMENT en JSON.

FICHE DE POSTE:
- Titre: {position.title}
- Description: {position.description[:1000]}
- Competences requises: {json.dumps(position.required_skills)}
- Niveau: {position.seniority_level}

CV PARSE:
{json.dumps(parsed_data, ensure_ascii=False)[:2000]}

PONDERATION DES CRITERES:
- skills_match : 50% du score global (competences techniques et fonctionnelles)
- experience_match : 30% du score global (annees + pertinence du parcours)
- education_match : 20% du score global (diplomes, certifications)
Le score global = (skills_match * 0.5) + (experience_match * 0.3) + (education_match * 0.2)

GUIDE D'INTERPRETATION DES SCORES:
- Score 80+ : excellent match, le candidat possede la grande majorite des competences requises et une experience tres pertinente
- Score 60+ : bon match, le candidat possede la plupart des competences requises, quelques lacunes mineures
- Score 40-59 : match partiel, lacunes significatives mais potentiel de progression
- Score <40 : faible correspondance avec le poste

INSTRUCTIONS D'EVALUATION:
- Valorise les competences transferables : une competence acquise dans un autre domaine reste une competence valide
- Ne penalise pas excessivement l'experience dans un secteur different si les competences techniques sont presentes
- Prends en compte les certifications et formations continues comme indicateurs de competences
- Evalue l'experience par rapport au niveau demande (junior/senior) — ne surpenalise pas un profil junior pour manque d'annees

REGLES STRICTES:
- Score de 0 a 100, base sur des criteres observables uniquement
- PAS d'inference de personnalite ou de motivation
- PAS de recommandation d'embauche
- Justifie chaque sous-score par des elements factuels du CV

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
    except (json.JSONDecodeError, IndexError):
        return {"score": 0, "explanation": {"error": "Scoring failed"}}
